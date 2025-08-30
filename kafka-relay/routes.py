from flask import Blueprint, Response, current_app, jsonify, request  # type: ignore

listen_bp = Blueprint("listen", __name__, url_prefix="/listen")


@listen_bp.post("/start")
def start() -> Response:
    data = request.get_json(force=True)
    listener_id = data["listenerId"]
    topic = data["topicName"]

    current_app.registry.start_listener(
        listener_id,
        topic,
        user=data.get("user"),  # NEW – may be str or list
        dealtype=data.get("dealtype"),  # NEW
    )
    return jsonify({"status": "started"}), 202


@listen_bp.post("/poll")
def poll() -> Response:
    data = request.get_json(force=True)

    listener_id = data["listenerId"]
    topic_name = data["topicName"]

    user_filter = data.get("user")
    dealtype_filter = data.get("dealtype")

    # create or “touch” listener (will update filters if supplied)
    current_app.registry.start_listener(
        listener_id,
        topic_name,
        user=user_filter,
        dealtype=dealtype_filter,
    )

    raw = current_app.registry.poll(listener_id, topic_name)

    # Build a NEW list so the shared dicts in IncomingQueue stay intact.
    messages = [{**rec, "ts": rec["ts"].isoformat()} for rec in raw]
    return jsonify(messages)