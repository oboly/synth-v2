include .env
export

schema-snapshot:
	mysqldump \
	-h $(DB_HOST) \
	-P $(DB_PORT) \
	-u $(DB_USER) \
	-p \
	--no-data \
	--routines \
	--triggers \
	$(DB_NAME) \
	> docs/database/schema_snapshot.sql
