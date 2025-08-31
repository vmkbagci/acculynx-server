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

    import asyncio
from kafka_relay.incoming_queue import IncomingQueue
from kafka_relay.parser_enricher import BatchEnricher
from kafka_relay.kafka_consumer import MQKafkaConsumer

# Create the outgoing queue for enriched items
incoming_queue = IncomingQueue()

# Create the batch enricher, outputting to the queue
enricher = BatchEnricher(
    out_queue=incoming_queue,  # Pass the instance!
    batch_size=20,
    idle_seconds=5.0,
    api_url="http://...",      # Set as appropriate
)

# Pass the enricher, NOT the queue, to KafkaConsumer
consumer = MQKafkaConsumer(env, topic, enricher=enricher)

    threading.Thread(target=_worker, daemon=True).start()
