import logging
import random
import asyncio
from typing import Optional
import xmltodict  # type: ignore
from confluent_kafka import Consumer, KafkaError, Message  # type: ignore

from app.model.incoming_queue import IncomingQueue
from .parser-enricher import BatchEnricher

LOGGING_API_URL = "http://172.17.0.3:5000/logging/generic"

SSL_CERT_PATH = "/projects/itrade-notification-service/certs/client/itrade.macbank.crt"
SSL_KEY_PATH = (
    "/projects/itrade-notification-service/certs/client/itrade.macbank-private.key"
)

bootstrap_servers_mapping = {
    "DEV": (
        "b-1.cfmmtsmtsmsgmskstagin.0q0n5f.c21.kafka.us-east-1.amazonaws.com:9094,"
        "b-2.cfmmtsmtsmsgmskstagin.0q0n5f.c21.kafka.us-east-1.amazonaws.com:9094,"
        "b-3.cfmmtsmtsmsgmskstagin.0q0n5f.c21.kafka.us-east-1.amazonaws.com:9094"
    ),
    "UAT": (
        "b-1.cfmmtsmtsmsgmskstagin.0q0n5f.c21.kafka.us-east-1.amazonaws.com:9094,"
        "b-2.cfmmtsmtsmsgmskstagin.0q0n5f.c21.kafka.us-east-1.amazonaws.com:9094,"
        "b-3.cfmmtsmtsmsgmskstagin.0q0n5f.c21.kafka.us-east-1.amazonaws.com:9094"
    ),
    "PROD": (
        "b-1.cfmmtsmtsmsgmskreleas.9jtoy2.c20.kafka.us-east-1.amazonaws.com:9094,"
        "b-2.cfmmtsmtsmsgmskreleas.9jtoy2.c20.kafka.us-east-1.amazonaws.com:9094,"
        "b-3.cfmmtsmtsmsgmskreleas.9jtoy2.c20.kafka.us-east-1.amazonaws.com:9094"
    ),
}

TOPIC = "deal.realtime.notify_01.nyc.relay"

TRADER_NAMES = ["amien", "kemal", "vidya"]


class MQKafkaConsumer:
    def __init__(
        self,
        env: str,
        topic: str,
        enricher: BatchEnricher,
        filter: Optional[str] = "energy_us_gas",
    ):
        self.env = env
        self.target_logging_endpoint = "n/a"
        self.topic = topic
        self.consumer = None
        self.bootstrap_servers = bootstrap_servers_mapping[self.env]
        self.filter = filter
        self.enricher = enricher

    def _connect(self) -> None:
        """
        Creates and configures the Kafka Consumer based on the environment and topic.
        """
        print("Attempting to establish connection")
        # Kafka Consumer configuration
        config = {
            "bootstrap.servers": self.bootstrap_servers,
            "group.id": f"itrade.vcloud-{self.env}",
            "security.protocol": "SSL",
            "ssl.ca.location": "/etc/ssl/certs/ca-certificates.crt",
            "ssl.certificate.location": SSL_CERT_PATH,
            "ssl.key.location": SSL_KEY_PATH,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
            "auto.commit.interval.ms": 0,
            "isolation.level": "read_committed",
        }

        # Create Consumer instance
        self.consumer = Consumer(config)
        assert self.consumer
        self.consumer.subscribe([self.topic])
        print(f"Connected to Kafka topic: {self.topic} in {self.env} environment.")

    async def _process_message(self, msg: Message) -> None:
        """
        Processes a Kafka message by enriching and submitting it to the downstream queue.
        """
        if self.filter in msg.value().decode("utf-8"):
            msg_as_dict = xmltodict.parse(
                f"<root>{msg.value().decode('utf-8')}</root>"
            )["root"]
            try:
                msg_as_dict["user"] = random.choice(TRADER_NAMES)
                self._log_msg_contents(msg_as_dict)
    
                # Submit raw message to BatchEnricher for enrichment and batching
                await self.enricher.submit({
                    "topic": self.topic,
                    "value": msg_as_dict,
                    "user": msg_as_dict["user"],
                    "dealtype": msg_as_dict["database_name"],
                })
    
                logging.info(f"Submitted message to batch enricher: {msg_as_dict}")
            except Exception as e:
                print(f"Error processing message: {e}")

    def _log_msg_contents(self, msg: dict[str, str]) -> None:
        log_entry = ""
        for key, val in msg.items():
            log_entry += f"{key} : {val}\n"
        # TODO: Define class for logging api interactions
        # response = requests.post(
        #     LOGGING_API_URL,
        #     json={
        #         "entries": [[log_entry]],
        #         "order": ["string"],
        #         "pattern": "string",
        #     },
        # )
        # response.raise_for_status()

def start(self) -> None:
    """
    Starts the Kafka Consumer loop to poll messages and process them.
    """
    if not self.consumer:
        print("Consumer not connected. Call _connect() first.")
        return
    try:
        while True:
            msg = self.consumer.poll(1.0)
            if msg is None:
                print("No msgs")
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    print(
                        "%% %s [%d] reached end at offset %d\n"
                        % (msg.topic(), msg.partition(), msg.offset())
                    )
                else:
                    print(msg.error())
            else:
                # Use asyncio.run to submit message asynchronously
                asyncio.run(self._process_message(msg))
    except KeyboardInterrupt:
        print("Consumer interrupted by user.")
    finally:
        print("Consumer Closing...")
        self.consumer.close()
