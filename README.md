# tweet-record-gae
Record tweets and actions in your timeline into Google Cloud SQL, by using Google App Engine platform.

## Requirements
- MySQL (Google Cloud SQL) >= 5.7
	- For N-gram CJK fulltext search
- Python (Google App Engine) >= 3.6
- Consumer {key | secret} for Official Twitter Client
	- Using undocumented API
- Pushover's API key <<https://pushover.net/>>
	- You can get notifications of mentions, favorites, etc.

## Install
1. Set up MySQL
	- google_cloud_sql_flags.txt
	- initialize.sql
2. Copy example files and modify them
	- config.json-example -> config.json
	- secret.yaml-example -> secret.yaml
3. Deploy to Google App Engine
	- `gcloud app deploy`
