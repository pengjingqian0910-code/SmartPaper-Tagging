"""
背景工作佇列（Background Worker）

提供一個全域單執行緒佇列，讓 UI 的重操作（標籤生成、圖譜建立）
不阻塞主執行緒，並統一顯示進度狀態。

用法：
    worker = BgWorker.get()
    worker.submit("標籤生成", fn, on_progress=cb, on_done=cb)
"""
from __future__ import annotations

import queue
import threading
from typing import Callable, Optional


class BgWorker:
    """單一背景執行緒佇列，依序執行提交的任務。"""

    _instance: Optional["BgWorker"] = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "BgWorker":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._current_task: Optional[str] = None
        self._listeners: list[Callable[[str, str], None]] = []
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    # ── Public API ────────────────────────────────────────────────────

    def submit(
        self,
        name: str,
        fn: Callable,
        *args,
        on_progress: Optional[Callable[[str], None]] = None,
        on_done: Optional[Callable[[bool, str], None]] = None,
        **kwargs,
    ) -> None:
        """
        將 fn(*args, **kwargs) 加入佇列。
        on_progress(msg): 任務中途呼叫
        on_done(success: bool, msg: str): 任務完成或失敗後呼叫
        """
        self._queue.put({
            "name": name, "fn": fn, "args": args, "kwargs": kwargs,
            "on_progress": on_progress, "on_done": on_done,
        })
        self._notify("queued", name)

    def add_listener(self, listener: Callable[[str, str], None]) -> None:
        """
        listener(event, task_name)
        event: "queued" | "started" | "done" | "error"
        """
        self._listeners.append(listener)

    def remove_listener(self, listener: Callable) -> None:
        self._listeners = [l for l in self._listeners if l is not listener]

    @property
    def is_busy(self) -> bool:
        return self._current_task is not None or not self._queue.empty()

    # ── Internal ──────────────────────────────────────────────────────

    def _loop(self):
        while True:
            task = self._queue.get()
            self._current_task = task["name"]
            self._notify("started", task["name"])
            try:
                kw = dict(task["kwargs"])
                if task["on_progress"]:
                    kw["progress_callback"] = task["on_progress"]
                result = task["fn"](*task["args"], **kw)
                self._notify("done", task["name"])
                if task["on_done"]:
                    task["on_done"](True, str(result or ""))
            except Exception as ex:
                self._notify("error", f"{task['name']}: {ex}")
                if task["on_done"]:
                    task["on_done"](False, str(ex))
            finally:
                self._current_task = None
                self._queue.task_done()

    def _notify(self, event: str, name: str):
        for listener in self._listeners:
            try:
                listener(event, name)
            except Exception:
                pass
