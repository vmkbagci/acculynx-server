import random
import threading
import time
from app.model.incoming_queue import IncomingQueue
from app.model.kafka_consumer import MQKafkaConsumer, TOPIC

USERS = ["kemal", "vidya", "amien", "mary"]
DEALTYPES = ["gas", "power", "oil", "ag"]


def start_mock_producer(incoming_queue: IncomingQueue, topic: str = "demo") -> None:
    def _worker() -> None:
        counter = 0
        while True:
            incoming_queue.publish(
                {
                    "topic": topic,
                    "value": f"msg-{counter}",
                    "user": random.choice(USERS),
                    "dealtype": random.choice(DEALTYPES),
                }
            )
            counter += 1
            time.sleep(random.uniform(0.5, 2.0))

    threading.Thread(target=_worker, daemon=True).start()


def start_kafka_consumer(incoming_queue: IncomingQueue, topic: str = TOPIC) -> None:
    def _worker() -> None:
        consumer = MQKafkaConsumer(env="DEV", topic=TOPIC, queue=incoming_queue)
        consumer._connect()
        consumer.start()

    threading.Thread(target=_worker, daemon=True).start()