.PHONY: run migrate

run:
	PYTHONPATH=./src python ./src/main.py

migrate:
	PYTHONPATH=./src python ./src/synth/db/migrate.py