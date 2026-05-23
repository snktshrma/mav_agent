from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from rclpy.executors import Executor
    from rclpy.node import Node


class ROSContext:
    """Process-wide singleton: one rclpy.init(), one executor, background spin."""

    _instance: ROSContext | None = None
    _class_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rclpy: Any = None
        self._executor: Executor | None = None
        self._spin_thread: threading.Thread | None = None
        self._node_refs = 0

    @classmethod
    def shared(cls) -> ROSContext:
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = ROSContext()
            return cls._instance

    @classmethod
    def reset_for_tests(cls) -> None:
        with cls._class_lock:
            if cls._instance is not None:
                cls._instance._force_shutdown()
                cls._instance = None

    def rclpy(self) -> Any:
        self._ensure()
        assert self._rclpy is not None
        return self._rclpy

    def _ensure(self) -> None:
        with self._lock:
            if self._rclpy is not None:
                return
            import rclpy
            from rclpy.executors import SingleThreadedExecutor

            self._rclpy = rclpy
            if not rclpy.ok():
                rclpy.init()
            self._executor = SingleThreadedExecutor()
            self._start_spin_thread()

    def _start_spin_thread(self) -> None:
        if self._spin_thread is not None and self._spin_thread.is_alive():
            return

        def _spin() -> None:
            while (
                self._rclpy is not None
                and self._rclpy.ok()
                and self._executor is not None
            ):
                self._executor.spin_once(timeout_sec=0.1)

        self._spin_thread = threading.Thread(
            target=_spin,
            name="mav_agent_ros_spin",
            daemon=True,
        )
        self._spin_thread.start()

    def create_node(self, name: str) -> Node:
        from rclpy.node import Node

        self._ensure()
        assert self._executor is not None
        node = Node(name)
        self._executor.add_node(node)
        with self._lock:
            self._node_refs += 1
        return node

    def remove_node(self, node: Node) -> None:
        with self._lock:
            if self._executor is None:
                return
            self._executor.remove_node(node)
            node.destroy_node()
            self._node_refs -= 1
            if self._node_refs <= 0:
                self._shutdown_unlocked()

    def _shutdown_unlocked(self) -> None:
        if self._rclpy is not None and self._rclpy.ok():
            self._rclpy.shutdown()
        self._executor = None
        self._spin_thread = None

    def _force_shutdown(self) -> None:
        with self._lock:
            self._node_refs = 0
            self._shutdown_unlocked()

    def spin_once(self, timeout_sec: float = 0.0) -> None:
        self._ensure()
        assert self._executor is not None
        self._executor.spin_once(timeout_sec=timeout_sec)

    def spin_until_future_complete(self, future, timeout_sec: float) -> bool:
        self._ensure()
        assert self._executor is not None
        self._executor.spin_until_future_complete(future, timeout_sec=timeout_sec)
        return future.done()
