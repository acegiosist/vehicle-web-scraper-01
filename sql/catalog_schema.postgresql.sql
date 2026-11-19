CREATE TABLE ai_run (
	id SERIAL NOT NULL, 
	batch_id VARCHAR(80), 
	model VARCHAR(40) NOT NULL, 
	prompt_version VARCHAR(20) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	n_requests INTEGER NOT NULL, 
	input_tokens INTEGER NOT NULL, 
	cache_read_tokens INTEGER NOT NULL, 
	cache_write_tokens INTEGER NOT NULL, 
	output_tokens INTEGER NOT NULL, 
	cost_usd FLOAT, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	ended_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_ai_run PRIMARY KEY (id), 
	CONSTRAINT uq_ai_run_batch_id UNIQUE (batch_id)
);

CREATE TABLE feature (
	id SERIAL NOT NULL, 
	code VARCHAR(40) NOT NULL, 
	category VARCHAR(20) NOT NULL, 
	name_es VARCHAR(80) NOT NULL, 
	name_en VARCHAR(80) NOT NULL, 
	CONSTRAINT pk_feature PRIMARY KEY (id), 
	CONSTRAINT uq_feature_code UNIQUE (code)
);

CREATE TABLE make (
	id SERIAL NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	slug VARCHAR(80) NOT NULL, 
	country_of_origin VARCHAR(60), 
	in_seed BOOLEAN NOT NULL, 
	created_by VARCHAR(10) NOT NULL, 
	CONSTRAINT pk_make PRIMARY KEY (id), 
	CONSTRAINT ck_make_created_by CHECK (created_by IN ('rule', 'ai', 'human')), 
	CONSTRAINT uq_make_slug UNIQUE (slug)
);

CREATE TABLE review_item (
	id SERIAL NOT NULL, 
	entity_type VARCHAR(20) NOT NULL, 
	entity_key VARCHAR(300) NOT NULL, 
	reason VARCHAR(40) NOT NULL, 
	detail TEXT, 
	proposal JSONB, 
	status VARCHAR(10) NOT NULL, 
	decided_by VARCHAR(80), 
	decided_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_review_item PRIMARY KEY (id), 
	CONSTRAINT uq_review_item_entity_type_entity_key_reason UNIQUE (entity_type, entity_key, reason), 
	CONSTRAINT ck_review_item_status CHECK (status IN ('open', 'approved', 'rejected', 'corrected'))
);

CREATE TABLE ai_decision (
	input_hash VARCHAR(64) NOT NULL, 
	ai_run_id INTEGER, 
	custom_id VARCHAR(64) NOT NULL, 
	item_kind VARCHAR(10) NOT NULL, 
	request JSONB NOT NULL, 
	response JSONB, 
	status VARCHAR(10) NOT NULL, 
	notes TEXT, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_ai_decision PRIMARY KEY (input_hash), 
	CONSTRAINT ck_ai_decision_status CHECK (status IN ('pending', 'accepted', 'review', 'rejected')), 
	CONSTRAINT fk_ai_decision_ai_run_id FOREIGN KEY(ai_run_id) REFERENCES ai_run (id) ON DELETE SET NULL
);

CREATE TABLE make_alias (
	alias_norm VARCHAR(120) NOT NULL, 
	make_id INTEGER NOT NULL, 
	method VARCHAR(10) NOT NULL, 
	confidence FLOAT CONSTRAINT ck_make_alias_confidence_range CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)), 
	CONSTRAINT pk_make_alias PRIMARY KEY (alias_norm), 
	CONSTRAINT ck_make_alias_method CHECK (method IN ('rule', 'ai', 'human')), 
	CONSTRAINT fk_make_alias_make_id FOREIGN KEY(make_id) REFERENCES make (id) ON DELETE CASCADE
);

CREATE TABLE model (
	id SERIAL NOT NULL, 
	make_id INTEGER NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	slug VARCHAR(120) NOT NULL, 
	match_key VARCHAR(160) NOT NULL, 
	name_locked BOOLEAN NOT NULL, 
	vehicle_class VARCHAR(10) NOT NULL, 
	default_body_style VARCHAR(20), 
	default_body_source VARCHAR(20), 
	verified BOOLEAN NOT NULL, 
	created_by VARCHAR(10) NOT NULL, 
	CONSTRAINT pk_model PRIMARY KEY (id), 
	CONSTRAINT uq_model_make_id_match_key UNIQUE (make_id, match_key), 
	CONSTRAINT ck_model_vehicle_class CHECK (vehicle_class IN ('car', 'moto', 'heavy')), 
	CONSTRAINT ck_model_default_body_style CHECK (default_body_style IS NULL OR default_body_style IN ('SUV', 'Sedan', 'Pickup', 'Hatchback', 'Coupe', 'Van', 'Convertible', 'Wagon', 'Truck', 'Minivan', 'Motorcycle')), 
	CONSTRAINT ck_model_default_body_source CHECK (default_body_source IS NULL OR default_body_source IN ('listing', 'title', 'consensus', 'ai_knowledge', 'human')), 
	CONSTRAINT ck_model_created_by CHECK (created_by IN ('rule', 'ai', 'human')), 
	CONSTRAINT fk_model_make_id FOREIGN KEY(make_id) REFERENCES make (id) ON DELETE CASCADE
);

CREATE INDEX ix_model_slug ON model (slug);

CREATE TABLE model_alias (
	make_id INTEGER NOT NULL, 
	alias_norm VARCHAR(160) NOT NULL, 
	model_id INTEGER NOT NULL, 
	method VARCHAR(10) NOT NULL, 
	confidence FLOAT CONSTRAINT ck_model_alias_confidence_range CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)), 
	CONSTRAINT pk_model_alias PRIMARY KEY (make_id, alias_norm), 
	CONSTRAINT ck_model_alias_method CHECK (method IN ('rule', 'ai', 'human')), 
	CONSTRAINT fk_model_alias_make_id FOREIGN KEY(make_id) REFERENCES make (id) ON DELETE CASCADE, 
	CONSTRAINT fk_model_alias_model_id FOREIGN KEY(model_id) REFERENCES model (id) ON DELETE CASCADE
);

CREATE TABLE trim (
	id SERIAL NOT NULL, 
	model_id INTEGER NOT NULL, 
	name VARCHAR(160) NOT NULL, 
	slug VARCHAR(160) NOT NULL, 
	match_key VARCHAR(160) NOT NULL, 
	name_locked BOOLEAN NOT NULL, 
	created_by VARCHAR(10) NOT NULL, 
	CONSTRAINT pk_trim PRIMARY KEY (id), 
	CONSTRAINT uq_trim_model_id_match_key UNIQUE (model_id, match_key), 
	CONSTRAINT ck_trim_created_by CHECK (created_by IN ('rule', 'ai', 'human')), 
	CONSTRAINT fk_trim_model_id FOREIGN KEY(model_id) REFERENCES model (id) ON DELETE CASCADE
);

CREATE TABLE trim_alias (
	model_id INTEGER NOT NULL, 
	alias_norm VARCHAR(240) NOT NULL, 
	trim_id INTEGER NOT NULL, 
	attrs JSONB, 
	method VARCHAR(10) NOT NULL, 
	confidence FLOAT CONSTRAINT ck_trim_alias_confidence_range CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)), 
	CONSTRAINT pk_trim_alias PRIMARY KEY (model_id, alias_norm), 
	CONSTRAINT ck_trim_alias_method CHECK (method IN ('rule', 'ai', 'human')), 
	CONSTRAINT fk_trim_alias_model_id FOREIGN KEY(model_id) REFERENCES model (id) ON DELETE CASCADE, 
	CONSTRAINT fk_trim_alias_trim_id FOREIGN KEY(trim_id) REFERENCES trim (id) ON DELETE CASCADE
);

CREATE TABLE variant (
	id SERIAL NOT NULL, 
	trim_id INTEGER NOT NULL, 
	variant_key VARCHAR(120) NOT NULL, 
	model_year INTEGER, 
	fuel_type VARCHAR(10), 
	transmission_type VARCHAR(10), 
	engine_displacement_l FLOAT, 
	body_style VARCHAR(20), 
	drivetrain VARCHAR(10), 
	engine_cylinders INTEGER, 
	horsepower_hp INTEGER, 
	doors INTEGER, 
	seats INTEGER, 
	fuel_tank_capacity_l FLOAT, 
	cargo_capacity_l INTEGER, 
	wheel_size_in INTEGER, 
	tire_size VARCHAR(20), 
	fuel_economy_kml FLOAT, 
	ev_range_km INTEGER, 
	ev_charging_speed_kw FLOAT, 
	airbags_count INTEGER, 
	screen_size_in FLOAT, 
	country_of_manufacture VARCHAR(60), 
	n_listings INTEGER NOT NULL, 
	needs_review BOOLEAN NOT NULL, 
	created_by VARCHAR(10) NOT NULL, 
	CONSTRAINT pk_variant PRIMARY KEY (id), 
	CONSTRAINT uq_variant_trim_id_variant_key UNIQUE (trim_id, variant_key), 
	CONSTRAINT ck_variant_body_style CHECK (body_style IS NULL OR body_style IN ('SUV', 'Sedan', 'Pickup', 'Hatchback', 'Coupe', 'Van', 'Convertible', 'Wagon', 'Truck', 'Minivan', 'Motorcycle')), 
	CONSTRAINT ck_variant_fuel_type CHECK (fuel_type IS NULL OR fuel_type IN ('Gasoline', 'Diesel', 'Hybrid', 'EV', 'CNG')), 
	CONSTRAINT ck_variant_transmission_type CHECK (transmission_type IS NULL OR transmission_type IN ('Manual', 'Automatic', 'CVT', 'DCT')), 
	CONSTRAINT ck_variant_drivetrain CHECK (drivetrain IS NULL OR drivetrain IN ('FWD', 'RWD', 'AWD', '4WD', '2WD')), 
	CONSTRAINT ck_variant_model_year_range CHECK (model_year IS NULL OR model_year BETWEEN 1900 AND 2100), 
	CONSTRAINT ck_variant_created_by CHECK (created_by IN ('rule', 'ai', 'human')), 
	CONSTRAINT fk_variant_trim_id FOREIGN KEY(trim_id) REFERENCES trim (id) ON DELETE CASCADE
);

CREATE TABLE listing (
	source_site VARCHAR(40) NOT NULL, 
	listing_id VARCHAR(120) NOT NULL, 
	variant_id INTEGER, 
	country VARCHAR(2), 
	source_url TEXT, 
	price FLOAT, 
	currency VARCHAR(3), 
	mileage_km INTEGER, 
	model_year INTEGER, 
	raw_make VARCHAR(120), 
	raw_model VARCHAR(160), 
	raw_trim VARCHAR(240), 
	match_method VARCHAR(10), 
	confidence FLOAT CONSTRAINT ck_listing_confidence_range CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)), 
	listed_at TIMESTAMP WITH TIME ZONE, 
	scraped_at TIMESTAMP WITH TIME ZONE, 
	raw JSONB, 
	CONSTRAINT pk_listing PRIMARY KEY (source_site, listing_id), 
	CONSTRAINT ck_listing_match_method CHECK (match_method IS NULL OR match_method IN ('rule', 'ai', 'human')), 
	CONSTRAINT fk_listing_variant_id FOREIGN KEY(variant_id) REFERENCES variant (id) ON DELETE SET NULL
);

CREATE INDEX ix_listing_variant_id ON listing (variant_id);

CREATE TABLE variant_feature (
	variant_id INTEGER NOT NULL, 
	feature_id INTEGER NOT NULL, 
	n_true INTEGER NOT NULL, 
	n_false INTEGER NOT NULL, 
	n_listings INTEGER NOT NULL, 
	CONSTRAINT pk_variant_feature PRIMARY KEY (variant_id, feature_id), 
	CONSTRAINT fk_variant_feature_variant_id FOREIGN KEY(variant_id) REFERENCES variant (id) ON DELETE CASCADE, 
	CONSTRAINT fk_variant_feature_feature_id FOREIGN KEY(feature_id) REFERENCES feature (id) ON DELETE CASCADE
);

CREATE TABLE variant_field_source (
	variant_id INTEGER NOT NULL, 
	field VARCHAR(40) NOT NULL, 
	value TEXT, 
	source VARCHAR(20) NOT NULL, 
	n_support INTEGER NOT NULL, 
	n_conflict INTEGER NOT NULL, 
	confidence FLOAT CONSTRAINT ck_variant_field_source_confidence_range CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)), 
	CONSTRAINT pk_variant_field_source PRIMARY KEY (variant_id, field), 
	CONSTRAINT ck_variant_field_source_source CHECK (source IN ('listing', 'title', 'consensus', 'ai_knowledge', 'human')), 
	CONSTRAINT fk_variant_field_source_variant_id FOREIGN KEY(variant_id) REFERENCES variant (id) ON DELETE CASCADE
);

CREATE TABLE variant_market (
	variant_id INTEGER NOT NULL, 
	country VARCHAR(2) NOT NULL, 
	first_listed TIMESTAMP WITH TIME ZONE, 
	last_listed TIMESTAMP WITH TIME ZONE, 
	n_listings INTEGER NOT NULL, 
	CONSTRAINT pk_variant_market PRIMARY KEY (variant_id, country), 
	CONSTRAINT fk_variant_market_variant_id FOREIGN KEY(variant_id) REFERENCES variant (id) ON DELETE CASCADE
);
