"""基于 asyncio.Queue 的异步事件队列。

架构职责：
- 作为 Controller 与各 BaseAgent 之间的异步消息传递层
- publish_async() 先将完整事件持久化到 GlobalEventStore，再异步放入内存队列
- 支持异步消费模式，避免同步回调阻塞
- 保持消息顺序和可靠性
"""

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, List, Optional, Set

from src.events.async_store import GlobalEventStore
from src.events.event import EventBase


@dataclass
class _Subscription:
    """单个订阅者的注册信息。"""
    subscriber_id: str                           # 订阅者唯一标识
    handler: Callable[[EventBase], Awaitable[None]]  # 异步事件处理回调
    event_types: Optional[List[str]]            # 关心的事件类型列表；None 表示接收所有类型
    visibility_scope: Optional[str]             # 只接收 visibility 中包含该值（或含 "all"）的事件；None 表示不过滤


class EventBus:
    """基于 asyncio.Queue 的异步事件队列。

    由 Controller 持有，负责：
    1. 维护订阅者注册表
    2. publish_async(event) 先落 GlobalEventStore，再异步放入队列
    3. 支持异步消费者从队列中获取消息
    4. 基于 event_type / visibility 做投递过滤

    注意：所有组件间的通信都通过此异步队列进行，确保消息的可靠传递。
    """

    def __init__(self, global_store: GlobalEventStore) -> None:
        """创建事件总线实例。

        Args:
            global_store: 全局事件落盘存储；publish 时会先写入该存储以保证可追溯性。
        """
        # 全局事件账本，publish 时先写入持久化
        self._global_store = global_store
        # 订阅者注册表：subscriber_id -> _Subscription
        self._subscriptions: Dict[str, _Subscription] = {}
        # 异步队列，用于消息传递
        self._queues: Dict[str, asyncio.Queue] = {"default": asyncio.Queue()}
        # 当前活跃的消费者集合
        self._active_consumers: Set[str] = set()

    async def publish_async(self, event: EventBase) -> None:
        """异步发布事件：先落账本，再异步放入队列。

        Args:
            event: 要发布的完整事件对象
        """
        # 步骤 1：先将完整事件持久化到全局账本
        # 改为异步方式处理持久化，以避免同步阻塞
        await self._global_store.append(event)

        # 步骤 2：异步放入队列供消费者处理
        for queue in self._queues.values():
            await queue.put(event)

        # 步骤 3：根据订阅关系分发给匹配的订阅者
        await self._dispatch_to_subscribers(event)

    async def _dispatch_to_subscribers(self, event: EventBase) -> None:
        """将事件分发给所有匹配的订阅者。"""
        subscriptions = list(self._subscriptions.values())
        if not subscriptions:
            return

        tasks = []
        for subscription in subscriptions:
            if self.filter_event_for_subscriber(event, subscription):
                tasks.append(asyncio.create_task(subscription.handler(event)))

        if not tasks:
            return

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                # 先保持失败隔离，避免单个订阅者阻断总线
                print(f"EventBus subscriber handler failed: {result}")

    def get_queue(self, queue_name: str = "default") -> asyncio.Queue:
        """获取指定名称的队列，用于异步消费。

        Args:
            queue_name: 队列名称，默认为 "default"

        Returns:
            asyncio.Queue: 指定名称的队列
        """
        if queue_name not in self._queues:
            self._queues[queue_name] = asyncio.Queue()
        return self._queues[queue_name]

    async def subscribe_async(
        self,
        subscriber_id: str,
        handler: Callable[[EventBase], Awaitable[None]],
        event_types: Optional[List[str]] = None,
        visibility_scope: Optional[str] = None,
    ) -> None:
        """异步注册订阅者。

        Args:
            subscriber_id: 订阅者唯一标识（同一 ID 重复订阅会覆盖旧注册）
            handler: 事件到达时的异步回调，接受单个 EventBase 参数
            event_types: 关心的事件类型列表（如 ["action", "system"]）；
                         None 表示接收所有类型
            visibility_scope: 只接收 visibility 包含此值（或含 "all"）的事件；
                              None 表示不做可见性过滤
        """
        self._subscriptions[subscriber_id] = _Subscription(
            subscriber_id=subscriber_id,
            handler=handler,
            event_types=event_types,
            visibility_scope=visibility_scope,
        )

    async def unsubscribe_async(self, subscriber_id: str) -> None:
        """异步取消订阅，若不存在则静默忽略。"""
        self._subscriptions.pop(subscriber_id, None)

    async def consume_async(self, queue_name: str = "default") -> EventBase:
        """异步消费队列中的下一个事件。

        Args:
            queue_name: 队列名称，默认为 "default"

        Returns:
            EventBase: 队列中的下一个事件
        """
        if queue_name not in self._queues:
            self._queues[queue_name] = asyncio.Queue()

        # 从队列获取事件
        event = await self._queues[queue_name].get()
        return event

    def filter_event_for_subscriber(self, event: EventBase, subscription: _Subscription) -> bool:
        """检查事件是否符合订阅者的过滤条件。

        Args:
            event: 待检查的事件
            subscription: 订阅信息

        Returns:
            bool: True 如果事件符合过滤条件，False 否则
        """
        # 过滤条件 A：事件类型匹配
        if subscription.event_types is not None and event.event_type not in subscription.event_types:
            return False

        # 过滤条件 B：可见性范围匹配
        if subscription.visibility_scope is not None:
            if "all" not in event.visibility and subscription.visibility_scope not in event.visibility:
                return False

        return True

    @property
    def subscriber_ids(self) -> List[str]:
        """返回当前所有已注册的订阅者 ID 列表（用于调试/测试）。"""
        return list(self._subscriptions.keys())

    @property
    def queue_sizes(self) -> Dict[str, int]:
        """返回所有队列的大小信息（用于监控/调试）。"""
        return {name: queue.qsize() for name, queue in self._queues.items()}
