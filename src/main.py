import uuid
from synth.logging.logging_setup import setup_logging, get_logger

def main() -> None:
    run_id = uuid.uuid4().hex[:12]
    setup_logging(run_id)

    log = get_logger("boot", run_id)
    log.info("synth_v2_started")

if __name__ == "__main__":
    main()