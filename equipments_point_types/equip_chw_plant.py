"""
Equipment definitions for chilled water plant.

Haystack hierarchy:
    equip → chilledWaterPlant → chiller
    equip → pump (chilledWaterRef → plant)

Each entry in EQUIPMENT contains:
    point_types  — point-type labels for this subtype; pass to build_tagconditions()
    equip_tags   — Haystack entity-level markers; go in the equipment_tag table
"""

EQUIPMENT = {

    # Chiller — evaporator-side points (condenser side in equip_cond_plant.py)
    'CHILLER': {
        'point_types': [
            'Chiller_run-cmd',
            'Chiller_run-sensor',
            'Chiller_flow',
            'Chiller_delta-pressure',
            'ChwEnt_watertemp',
            'ChwLvg_watertemp',
            'ChwLvg_watertemp-sp',
            'IsoValve_cmd',
            'IsoValve_run-sensor',
            'IsoValve_pos',
        ],
        'equip_tags': ['equip', 'chiller', 'chilled', 'water'],
    },

    # Chilled water pump
    'CHW-PUMP': {
        'point_types': [
            'ChwPump_run',
            'ChwPump_cmd',
            'ChwPump_enable-cmd',
            'ChwPump_speed',
            'ChwPump_waterflow',
            'ChwPump_diff-pressure',
            'ChwPump_dis-pressure',
            'ChwPump_suc-pressure',
        ],
        'equip_tags': ['equip', 'pump', 'chilled', 'water'],
    },
}
