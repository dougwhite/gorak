select e.entity_name as application_name, a.proc_start as start_component, e.short_remark
from ii_applications a
left join ii_entities e on a.entity_id = e.entity_id
\p\g
