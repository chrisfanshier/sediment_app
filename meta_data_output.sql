SELECT  
c.cruise, 
v.vessel_name, 
c.date, 
c.time_launched, 
c.time_on_bottom, 
c.time_recovered, 
c.latitude, 
c.longitude, 
c.water_depth_m, 
ct.core_type_name, 
s.section_number,
c.core_name,
c.core_name ||'-'|| s.section_number AS section_name, 
s.section_length,
s.top_cum_length,
s.bottom_cum_length,
c.station,
c.notes
FROM sections s
FULL OUTER JOIN cores c ON s.core_id = c.core_id
LEFT JOIN core_types ct ON c.core_type_id = ct.core_type_id
LEFT JOIN vessels v ON c.vessel_id = v.vessel_id
WHERE c.cruise = 'SKQ202512S';