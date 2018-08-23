-- CREATE DATABASE tweet_record;
-- use tweet_record;

CREATE TABLE tweets (
	json_data JSON NOT NULL,
	expanded_text VARCHAR(8190),
	id BIGINT UNSIGNED AS (json_data->>'$.id') STORED PRIMARY KEY,
	created_at DATETIME AS (str_to_date(json_data->>'$.created_at', '%a %b %d %H:%i:%s +0000 %Y')) VIRTUAL NOT NULL,
	in_reply_to_status_id BIGINT UNSIGNED AS (json_unquote(NULLIF(json_data->'$.in_reply_to_status_id', CAST('null' AS JSON)))) VIRTUAL,
	in_reply_to_user_id BIGINT UNSIGNED AS (json_unquote(NULLIF(json_data->'$.in_reply_to_user_id', CAST('null' AS JSON)))) VIRTUAL,
	retweeted_status_id BIGINT UNSIGNED AS (json_unquote(NULLIF(json_data->'$.retweeted_status.id', CAST('null' AS JSON)))) VIRTUAL,
	quoted_status_id BIGINT UNSIGNED AS (json_unquote(NULLIF(json_data->'$.quoted_status_id', CAST('null' AS JSON)))) VIRTUAL,
	user_id BIGINT UNSIGNED AS (json_data->>'$.user.id') VIRTUAL NOT NULL,
	user_screen_name VARCHAR(63) AS (json_data->>'$.user.screen_name') VIRTUAL NOT NULL,
	user_name VARCHAR(63) AS (json_data->>'$.user.name') STORED NOT NULL,
	user_protected BOOLEAN AS (json_data->>'$.user.protected'='true') STORED NOT NULL,
	has_polls BOOLEAN AS (json_data->>'$.card.binding_values.choice1_label' IS NOT NULL) STORED NOT NULL,
	has_media BOOLEAN AS (json_data->>'$.extended_entities.media' IS NOT NULL) STORED NOT NULL,
	FULLTEXT INDEX (expanded_text) WITH PARSER ngram,
	FULLTEXT INDEX (user_name) WITH PARSER ngram,
	INDEX (created_at),
	INDEX (in_reply_to_status_id),
	INDEX (in_reply_to_user_id),
	INDEX (retweeted_status_id),
	INDEX (quoted_status_id),
	INDEX (user_id),
	INDEX (user_screen_name)
) ROW_FORMAT=COMPRESSED;

CREATE TABLE places (
	json_data JSON NOT NULL,
	tweet_id BIGINT UNSIGNED AS (json_data->>'$.id') STORED PRIMARY KEY,
	place_id VARCHAR(63) AS (json_data->>'$.place.id') VIRTUAL NOT NULL,
	place_bounding_box POLYGON AS (ST_GeomFromGeoJson(json_array_append(json_data->'$.place.bounding_box', '$.coordinates[0]', json_data->'$.place.bounding_box.coordinates[0][0]'))) STORED NOT NULL,
	SPATIAL INDEX (place_bounding_box),
	INDEX (tweet_id),
	INDEX (place_id)
) ROW_FORMAT=COMPRESSED;

CREATE TABLE coordinates (
	json_data JSON NOT NULL,
	tweet_id BIGINT UNSIGNED AS (json_data->>'$.id') STORED PRIMARY KEY,
	coordinates POINT AS (ST_GeomFromGeoJson(json_data->'$.coordinates')) STORED NOT NULL,
	SPATIAL INDEX (coordinates),
	INDEX (tweet_id)
) ROW_FORMAT=COMPRESSED;

-- 標準stopword回避用table
CREATE TABLE INNODB_FT_STOPWORD (
	value VARCHAR(30)
);

-- about_me.json 記録用
CREATE TABLE actions (
	json_data JSON NOT NULL,
	id BIGINT UNSIGNED AS (json_data->>'$.min_position') STORED PRIMARY KEY,
	created_at DATETIME AS (str_to_date(json_data->>'$.created_at', '%a %b %d %H:%i:%s +0000 %Y')) VIRTUAL NOT NULL,
	action VARCHAR(63) AS (json_data->>'$.action') VIRTUAL NOT NULL,
	INDEX (action)
) ROW_FORMAT=COMPRESSED;

