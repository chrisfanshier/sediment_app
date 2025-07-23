-- STEP 1: Copy data from 138 (incorrect name, correct data) to 139 (correct name)
UPDATE cores
SET
    latitude = c2.latitude,
    longitude = c2.longitude,
    water_depth_m = c2.water_depth_m,
    date = c2.date,
    notes = c2.notes,
    pullout_tension = c2.pullout_tension,
    cruise = c2.cruise,
    leg = c2.leg,
    station = c2.station,
    observer = c2.observer,
    time_launched = c2.time_launched,
    time_on_bottom = c2.time_on_bottom,
    time_recovered = c2.time_recovered,
    wire_out_on_bottom = c2.wire_out_on_bottom,
    max_wire_out = c2.max_wire_out,
    tension_at_surface = c2.tension_at_surface,
    tension_near_bottom = c2.tension_near_bottom,
    tension_on_bottom = c2.tension_on_bottom,
    vessel_id = c2.vessel_id,
    core_type_id = c2.core_type_id,
    core_length = c2.core_length,
    trigger_line_length = c2.trigger_line_length,
    trigger_core_length = c2.trigger_core_length,
    trigger_weight = c2.trigger_weight,
    scope = c2.scope,
    pig_weights = c2.pig_weights,
    vibracorer_model = c2.vibracorer_model,
    barrel_diameter = c2.barrel_diameter,
    liner_diameter = c2.liner_diameter,
    wire_type = c2.wire_type,
    impact_speed = c2.impact_speed
FROM cores c2
WHERE cores.core_id = 139
  AND c2.core_id = 138;

-- STEP 2: Update all files to point to the correct core_id
UPDATE files
SET core_id = 139
WHERE core_id = 138;

-- STEP 3: (Optional) Delete the incorrect core entry
DELETE FROM cores
WHERE core_id = 138;