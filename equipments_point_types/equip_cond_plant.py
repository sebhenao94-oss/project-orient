"""
Equipment definitions for condenser water plant.

Haystack hierarchy:
    equip → condenserWaterPlant → coolingTower
    equip → pump (condenserWaterRef → plant)

Each entry in EQUIPMENT contains:
    point_types  — point-type labels for this subtype; pass to build_tagconditions()
    equip_tags   — Haystack entity-level markers; go in the equipment_tag table
"""

EQUIPMENT = {

    # Cooling tower
    'COOLING-TOWER': {
        'point_types': [
            'CT-F_run-sensor',
            'CT-F_speed',
            'CT-F_enable-cmd',
            'CT-F_cmd',
            'CT_wetbulb',
            'CT-Ent_watertemp',
            'CT-Lvg_watertemp',
            'CT-Lvg_watertemp-sp',
            'CT-OA_airtemp',
            'CT-OA_airtemp-wb',
            'CT-Basin-watertemp',
            'CT-Basin_heat-cmd',
            'CT-Basin_run-sensor',
        ],
        'equip_tags': ['equip', 'coolingTower', 'condenser', 'water'],
    },

    # Condenser water pump
    'COND-PUMP': {
        'point_types': [
            'CondPump_run',
            'CondPump_cmd',
            'CondPump_enable-cmd',
            'CondPump_speed',
            'CondPump_waterflow',
            'CondPump_diff-pressure',
            'CondPump_dis-pressure',
            'CondPump_suc-pressure',
        ],
        'equip_tags': ['equip', 'pump', 'condenser', 'water'],
    },
}
