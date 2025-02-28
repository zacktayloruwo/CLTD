import psycopg2
from config import config as conf

# connect to database
connection = psycopg2.connect(
	"""host='{host}' port='{port}' dbname='{dbname}'
		user='{user}' password='{password}'
	""".format(
		host = conf['pg']['host'],
		port = conf['pg']['port'],
		dbname = conf['pg']['database'],
		user = conf['pg']['user'],
		password = conf['pg']['password']
	)
)
connection.autocommit = True

def update_crosswalk(crosswalk_table, source, target, weights, source_id, target_id):

	for weight in weights:

		print("Updating weights for w_" + weight)

		query = f"""

		DROP TABLE IF EXISTS x_{crosswalk_table}_1_{weight};
		CREATE TABLE x_{crosswalk_table}_1_{weight} AS (
		WITH sum_source_{weight} AS (SELECT 
			source_ctuid,
			COUNT(*) AS source_count,
			SUM(w_{weight}) AS sum_w_{weight}
			FROM x_{crosswalk_table}
			WHERE source_ctuid != '-1'	
			GROUP BY source_ctuid
			ORDER BY sum_w_{weight} DESC, source_ctuid),
		sum_source_{weight}_join AS (SELECT 
			x_{crosswalk_table}.*,
			sum_source_{weight}.sum_w_{weight},
			x_{crosswalk_table}.w_{weight} / (sum_source_{weight}.sum_w_{weight} + 0.000000000000001) AS w_{weight}_1,
			sum_source_{weight}.source_count
			FROM x_{crosswalk_table}
			LEFT JOIN sum_source_{weight}
			ON x_{crosswalk_table}.source_ctuid = sum_source_{weight}.source_ctuid),
		sum_target AS (SELECT 
			target_ctuid AS target_ctuid,
			COUNT(*) AS target_count,
			SUM(w_{weight}) AS sum_target_w_{weight},
			MAX(w_{weight}) AS max_target_w_{weight}
			FROM x_{crosswalk_table} WHERE target_ctuid != '-1'
			GROUP BY target_ctuid
			ORDER BY target_ctuid),
		x_ct_reduce AS (SELECT 
			sum_source_{weight}_join.source_ctuid,
			sum_source_{weight}_join.target_ctuid,
			ROUND(w_{weight}_1::numeric, 10) AS w_{weight}_1
			FROM sum_source_{weight}_join LEFT JOIN sum_target
			ON sum_source_{weight}_join.target_ctuid = sum_target.target_ctuid
			WHERE 
			source_count = 1 OR 
			target_count = 1 OR 
			sum_source_{weight}_join.target_ctuid = '-1' OR
			sum_source_{weight}_join.source_ctuid = '-1' OR
			w_{weight}_1 > 0.042 OR
			sum_source_{weight}_join.target_ctuid IN (
				SELECT target_ctuid FROM x_{crosswalk_table} WHERE source_ctuid = '-1'
				AND target_ctuid NOT IN (SELECT target_ctuid FROM x_{crosswalk_table} WHERE source_ctuid = '-1')
			) OR
			max_target_w_{weight} <= 0.042
			),
		sum_source_{weight}_1 AS (SELECT
			source_ctuid,
			SUM(w_{weight}_1) AS sum_w_{weight}
			FROM x_ct_reduce
			GROUP BY source_ctuid
			ORDER BY sum_w_{weight} DESC, source_ctuid),
		x_ct_ready AS (SELECT 
			x_ct_reduce.source_ctuid,
			x_ct_reduce.target_ctuid,
			ROUND(x_ct_reduce.w_{weight}_1 / (sum_source_{weight}_1.sum_w_{weight} + 0.0000000000000001), 10) AS w_{weight}
			FROM x_ct_reduce
			LEFT JOIN sum_source_{weight}_1
			ON x_ct_reduce.source_ctuid = sum_source_{weight}_1.source_ctuid),
		extra_target AS (
			SELECT 
			'-1' AS source_ctuid,
			{target_id} AS target_ctuid,
			0 AS w_{weight}
			FROM {target}
			WHERE {target_id} NOT IN (SELECT DISTINCT target_ctuid FROM x_ct_ready)
			ORDER BY {target_id}),
		extra_source AS (
			SELECT 
			{source_id} AS source_ctuid,
			'-1' AS target_ctuid,
			1 AS w_{weight}
			FROM {source}
			WHERE {source_id} NOT IN (SELECT DISTINCT source_ctuid FROM x_ct_ready)
			ORDER BY {source_id})
		SELECT * FROM x_ct_ready
		UNION ALL
		SELECT * FROM extra_target
		UNION ALL
		SELECT * FROM extra_source
		);

		UPDATE x_{crosswalk_table}_1_{weight} SET w_{weight} = -1 WHERE source_ctuid = '-1'; 
		"""

		with connection.cursor() as cursor:
			cursor.execute(query)

	print("saving output as " + crosswalk_table)

	if len(weights) > 1:

		query = f"""
		DROP TABLE IF EXISTS {crosswalk_table};
		CREATE TABLE {crosswalk_table} AS (
			SELECT 
			x_{crosswalk_table}_1_{weights[0]}.source_ctuid AS sc,
			x_{crosswalk_table}_1_{weights[0]}.target_ctuid AS tc,
			x_{crosswalk_table}_1_{weights[1]}.source_ctuid,
			x_{crosswalk_table}_1_{weights[1]}.target_ctuid,
			x_{crosswalk_table}_1_{weights[0]}.w_{weights[0]},
			x_{crosswalk_table}_1_{weights[1]}.w_{weights[1]}
			FROM x_{crosswalk_table}_1_{weights[0]} 
			FULL OUTER JOIN x_{crosswalk_table}_1_{weights[1]}
			ON x_{crosswalk_table}_1_{weights[0]}.source_ctuid = x_{crosswalk_table}_1_{weights[1]}.source_ctuid
			AND x_{crosswalk_table}_1_{weights[0]}.target_ctuid = x_{crosswalk_table}_1_{weights[1]}.target_ctuid
		);

		UPDATE {crosswalk_table} SET w_{weights[0]} = 0 WHERE w_{weights[0]} IS NULL;
		UPDATE {crosswalk_table} SET w_{weights[1]} = 0 WHERE w_{weights[1]} IS NULL;
		UPDATE {crosswalk_table} SET source_ctuid = sc WHERE source_ctuid IS NULL;
		UPDATE {crosswalk_table} SET target_ctuid = tc WHERE target_ctuid IS NULL;
		ALTER TABLE {crosswalk_table} DROP COLUMN sc;
		ALTER TABLE {crosswalk_table} DROP COLUMN tc;

		DROP TABLE IF EXISTS x_{crosswalk_table}_1_{weights[0]};
		DROP TABLE IF EXISTS x_{crosswalk_table}_1_{weights[1]};

		UPDATE {crosswalk_table}
		SET w_{weights[1]} = w_{weights[0]}
		WHERE source_ctuid IN (SELECT source_ctuid FROM ct_2011_2016 WHERE w_{weights[1]} = 0 AND w_{weights[0]} > 0);

		UPDATE {crosswalk_table}
		SET w_{weights[0]} = w_{weights[1]}
		WHERE source_ctuid IN (SELECT source_ctuid FROM ct_2011_2016 WHERE w_{weights[0]} = 0 AND w_{weights[1]} > 0);

		UPDATE {crosswalk_table}
		SET w_{weights[1]} = -1
		WHERE w_{weights[0]} = -1 AND w_{weights[1]} = 0;

		UPDATE {crosswalk_table}
		SET w_{weights[0]} = -1
		WHERE w_{weights[1]} = -1 AND w_{weights[0]} = 0;

		UPDATE {crosswalk_table}
		SET w_{weights[0]} = w_{weights[1]}
		WHERE source_ctuid IN
		(SELECT source_ctuid FROM {crosswalk_table} WHERE (w_{weights[0]} = 0 AND w_{weights[1]} > 0));

		UPDATE {crosswalk_table}
		SET w_{weights[1]} = w_{weights[0]}
		WHERE source_ctuid IN
		(SELECT source_ctuid FROM {crosswalk_table} WHERE (w_{weights[0]} > 0 AND w_{weights[1]} = 0));
		"""

	elif len(weights) == 1:

		query = f"""
		DROP TABLE IF EXISTS {crosswalk_table};
		CREATE TABLE {crosswalk_table} AS (
			SELECT * FROM x_{crosswalk_table}_1_{weights[0]}
		);

		DROP TABLE IF EXISTS x_{crosswalk_table}_1_{weights[0]};
		"""

	else:

		query = ""

	with connection.cursor() as cursor:
		cursor.execute(query)


	print("running list of manuel updates:")

	update_query = './updates.sql'

	with open(update_query) as file:
		query = file.read()

	with connection.cursor() as cursor:
		cursor.execute(query)
	



	print("filling holes: " + crosswalk_table)

	if len(weights) > 1:

		query = f"""

		DROP TABLE IF EXISTS temp_to_insert;
		CREATE TABLE temp_to_insert AS
		WITH target_count AS (SELECT 
			target_ctuid,
			COUNT(*) AS target_count 
			FROM {crosswalk_table}
			GROUP BY target_ctuid
			ORDER BY target_ctuid), 
		possible_holes AS (
			SELECT * FROM {crosswalk_table}
			WHERE source_ctuid = '-1'
			AND target_ctuid IN (SELECT target_ctuid FROM target_count WHERE target_count = 1)
		),
		area_intersection AS (
			SELECT 
			{source}.{source_id} AS source_ctuid,
			{target}.{target_id} AS target_ctuid,
			ST_Area(ST_Intersection(ST_MakeValid({source}.geom),ST_MakeValid({target}.geom))::geography) AS area
			FROM {source} LEFT JOIN {target}
			ON ST_Intersects(ST_MakeValid({source}.geom),ST_MakeValid({target}.geom))
			WHERE {source}.geom && {target}.geom
			AND {target}.{target_id} IN (SELECT target_ctuid FROM possible_holes)
		),
		area_intersection_reduce AS (SELECT 
			source_ctuid,
			target_ctuid,
			area
			FROM area_intersection g1
			WHERE area = ( SELECT MAX( g2.area )
						FROM area_intersection g2
						WHERE g1.target_ctuid = g2.target_ctuid )
			ORDER BY target_ctuid
		),
		source_union as (
			SELECT ST_Union(geom) as geom FROM {source}
		),
		target_contained AS (
			SELECT {target}.{target_id} as target_ctuid
			FROM {target}, source_union
			WHERE ST_Within({target}.geom, source_union.geom)
			ORDER BY {target}.{target_id}
		),
		insert_and_delete AS (
		SELECT
			source_ctuid,
			target_ctuid,
			0.0000000001 AS w_{weights[0]},
			0.0000000001 AS w_{weights[1]},
			'id' AS f
			FROM area_intersection_reduce
			WHERE target_ctuid IN (SELECT target_ctuid FROM target_contained)
		),
		insert_only AS (
			SELECT
			source_ctuid,
			target_ctuid,
			0.0000000001 AS w_{weights[0]},
			0.0000000001 AS w_{weights[1]},
			'i' AS f
			FROM area_intersection_reduce
			WHERE area > 750000
			AND target_ctuid NOT IN (SELECT target_ctuid FROM insert_and_delete)
		)
		SELECT * FROM insert_and_delete
		UNION
		SELECT * FROM insert_only;

		INSERT INTO {crosswalk_table}
		SELECT
		source_ctuid,
		target_ctuid,
		w_{weights[0]},
		w_{weights[1]}
		FROM temp_to_insert;

		DELETE FROM {crosswalk_table}
		WHERE source_ctuid = '-1'
		AND target_ctuid IN (SELECT target_ctuid FROM temp_to_insert WHERE f = 'id');

		UPDATE {crosswalk_table}
		SET w_{weights[0]} = ROUND(w_{weights[0]}, 10);

		UPDATE {crosswalk_table}
		SET w_{weights[0]} = w_{weights[0]} + 0.0000000001 WHERE w_{weights[0]} = 0.0000000000;

		UPDATE {crosswalk_table}
		SET w_{weights[1]} = ROUND(w_{weights[1]}, 10);

		UPDATE {crosswalk_table}
		SET w_{weights[1]} = w_{weights[1]} + 0.0000000001 WHERE w_{weights[1]} = 0.0000000000;

		DROP TABLE IF EXISTS temp_to_insert;
		"""

	elif len(weights) == 1:

		query = f"""

		DROP TABLE IF EXISTS temp_to_insert;
		CREATE TABLE temp_to_insert AS
		WITH target_count AS (SELECT 
			target_ctuid,
			COUNT(*) AS target_count 
			FROM {crosswalk_table}
			GROUP BY target_ctuid
			ORDER BY target_ctuid), 
		possible_holes AS (
			SELECT * FROM {crosswalk_table}
			WHERE source_ctuid = '-1'
			AND target_ctuid IN (SELECT target_ctuid FROM target_count WHERE target_count = 1)
		),
		area_intersection AS (
			SELECT 
			{source}.{source_id} AS source_ctuid,
			{target}.{target_id} AS target_ctuid,
			ST_Area(ST_Intersection(ST_MakeValid({source}.geom),ST_MakeValid({target}.geom))::geography) AS area
			FROM {source} LEFT JOIN {target}
			ON ST_Intersects(ST_MakeValid({source}.geom),ST_MakeValid({target}.geom))
			WHERE {source}.geom && {target}.geom
			AND {target}.{target_id} IN (SELECT target_ctuid FROM possible_holes)
		),
		area_intersection_reduce AS (SELECT 
			source_ctuid,
			target_ctuid,
			area
			FROM area_intersection g1
			WHERE area = ( SELECT MAX( g2.area )
						FROM area_intersection g2
						WHERE g1.target_ctuid = g2.target_ctuid )
			ORDER BY target_ctuid
		),
		source_union as (
			SELECT ST_Union(geom) as geom FROM {source}
		),
		target_contained AS (
			SELECT {target}.{target_id} as target_ctuid
			FROM {target}, source_union
			WHERE ST_Within({target}.geom, source_union.geom)
			ORDER BY {target}.{target_id}
		),
		insert_and_delete AS (
		SELECT
			source_ctuid,
			target_ctuid,
			0.0000000001 AS w_{weights[0]},
			'id' AS f
			FROM area_intersection_reduce
			WHERE target_ctuid IN (SELECT target_ctuid FROM target_contained)
		),
		insert_only AS (
			SELECT
			source_ctuid,
			target_ctuid,
			0.0000000001 AS w_{weights[0]},
			'i' AS f
			FROM area_intersection_reduce
			WHERE area > 750000
			AND target_ctuid NOT IN (SELECT target_ctuid FROM insert_and_delete)
		)
		SELECT * FROM insert_and_delete
		UNION
		SELECT * FROM insert_only;

		INSERT INTO {crosswalk_table}
		SELECT
		source_ctuid,
		target_ctuid,
		w_{weights[0]}
		FROM temp_to_insert;

		DELETE FROM {crosswalk_table}
		WHERE source_ctuid = '-1'
		AND target_ctuid IN (SELECT target_ctuid FROM temp_to_insert WHERE f = 'id');

		UPDATE {crosswalk_table}
		SET w_{weights[0]} = ROUND(w_{weights[0]}, 10);

		UPDATE {crosswalk_table}
		SET w_{weights[0]} = w_{weights[0]} + 0.0000000001 WHERE w_{weights[0]} = 0.0000000000;

		DROP TABLE IF EXISTS temp_to_insert;
		"""

	else:

		query = ""

	with connection.cursor() as cursor:
		cursor.execute(query)


	with connection.cursor() as cursor:
		cursor.execute(f"SELECT COUNT(DISTINCT source_ctuid) FROM {crosswalk_table};")
		result = cursor.fetchone();
		print(result)
	with connection.cursor() as cursor:
		cursor.execute(f"SELECT COUNT(DISTINCT {source_id}) FROM {source};")
		result = cursor.fetchone();
		print(result)
	with connection.cursor() as cursor:
		cursor.execute(f"SELECT COUNT(DISTINCT target_ctuid) FROM {crosswalk_table};")
		result = cursor.fetchone();
		print(result)
	with connection.cursor() as cursor:
		cursor.execute(f"SELECT COUNT(DISTINCT {target_id}) FROM {target};")
		result = cursor.fetchone();
		print(result)






update_crosswalk("ct_1951_1956", "in_1951_ct", "in_1956_ct", ["area"], "geosid", "geosid")
update_crosswalk("ct_1951_2021", "in_1951_ct", "in_2021_cbf_ct", ["area"], "geosid", "ctuid")

update_crosswalk("ct_1956_1961", "in_1956_ct", "in_1961_ct", ["area"], "geosid", "geosid")
update_crosswalk("ct_1956_2021", "in_1956_ct", "in_2021_cbf_ct", ["area"], "geosid", "ctuid")

update_crosswalk("ct_1961_1966", "in_1961_ct", "in_1966_ct", ["area"], "geosid", "geosid")
update_crosswalk("ct_1961_2021", "in_1961_ct", "in_2021_cbf_ct", ["area"], "geosid", "ctuid")

update_crosswalk("ct_1966_1971", "in_1966_ct", "in_1971_cbf_ct", ["area"], "geosid", "geosid")
update_crosswalk("ct_1966_2021", "in_1966_ct", "in_2021_cbf_ct", ["area"], "geosid", "ctuid")

update_crosswalk("ct_1971_1976", "in_1971_cbf_ct", "in_1976_cbf_ct", ["pop", "dwe"], "geosid", "geosid")
update_crosswalk("ct_1971_2021", "in_1971_cbf_ct", "in_2021_cbf_ct", ["pop", "dwe"], "geosid", "ctuid")

update_crosswalk("ct_1976_1981", "in_1976_cbf_ct", "in_1981_cbf_ct", ["pop", "dwe"], "geosid", "geosid")
update_crosswalk("ct_1976_2021", "in_1976_cbf_ct", "in_2021_cbf_ct", ["pop", "dwe"], "geosid", "ctuid")

update_crosswalk("ct_1981_1986", "in_1981_cbf_ct", "in_1986_cbf_ct", ["pop", "dwe"], "geosid", "geosid")
update_crosswalk("ct_1981_2021", "in_1981_cbf_ct", "in_2021_cbf_ct", ["pop", "dwe"], "geosid", "ctuid")

update_crosswalk("ct_1986_1991", "in_1986_cbf_ct", "in_1991_cbf_ct_moved_clipped", ["pop", "dwe"], "geosid", "geosid")
update_crosswalk("ct_1986_2021", "in_1986_cbf_ct", "in_2021_cbf_ct", ["pop", "dwe"], "geosid", "ctuid")

update_crosswalk("ct_1991_1996", "in_1991_cbf_ct_moved_clipped", "in_1996_cbf_ct_moved_clipped", ["pop", "dwe"], "geosid", "geosid")
update_crosswalk("ct_1991_2021", "in_1991_cbf_ct_moved_clipped", "in_2021_cbf_ct", ["pop", "dwe"], "geosid", "ctuid")

update_crosswalk("ct_1996_2001", "in_1996_cbf_ct_moved_clipped", "in_2001_cbf_ct", ["pop", "dwe"], "geosid", "ctuid")
update_crosswalk("ct_1996_2021", "in_1996_cbf_ct_moved_clipped", "in_2021_cbf_ct", ["pop", "dwe"], "geosid", "ctuid")

update_crosswalk("ct_2001_2006", "in_2001_cbf_ct", "in_2006_cbf_ct", ["pop", "dwe"], "ctuid", "ctuid")
update_crosswalk("ct_2001_2021", "in_2001_cbf_ct", "in_2021_cbf_ct", ["pop", "dwe"], "ctuid", "ctuid")

update_crosswalk("ct_2006_2011", "in_2006_cbf_ct", "in_2011_cbf_ct", ["pop", "dwe"], "ctuid", "ctuid")
update_crosswalk("ct_2006_2021", "in_2006_cbf_ct", "in_2021_cbf_ct", ["pop", "dwe"], "ctuid", "ctuid")

update_crosswalk("ct_2011_2016", "in_2011_cbf_ct", "in_2016_cbf_ct", ["pop", "dwe"], "ctuid", "ctuid")
update_crosswalk("ct_2011_2021", "in_2011_cbf_ct", "in_2021_cbf_ct", ["pop", "dwe"], "ctuid", "ctuid")

update_crosswalk("ct_2016_2021", "in_2016_cbf_ct", "in_2021_cbf_ct", ["pop", "dwe"], "ctuid", "ctuid")
