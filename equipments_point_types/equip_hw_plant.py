"""
Equipment definitions for hot water plant.

Haystack hierarchy:
    equip → hotWaterPlant → boiler
    equip → pump (hotWaterRef → plant)

Each entry in EQUIPMENT contains:
    point_types  — point-type labels for this subtype; pass to build_tagconditions()
    equip_tags   — Haystack entity-level markers; go in the equipment_tag table
"""

EQUIPMENT = {

    # Boiler
    'BOILER': {
        'point_types': [
            'Boiler_run-sensor',
            'Boiler_enable-cmd',
            'HwEnt_watertemp',
            'HwLvg_watertemp',
            'HwLvg_watertemp-sp',
        ],
        'equip_tags': ['equip', 'boiler', 'hot', 'water'],
    },

    # Hot water pump
    'HW-PUMP': {
        'point_types': [
            'HwPump_run',
            'HwPump_speed-cmd',
            'HwPump_speed',
            'HwPump_diff-pressure',
            'HwPump_dis-pressure',
            'HwPump_suc-pressure',
        ],
        'equip_tags': ['equip', 'pump', 'hot', 'water'],
    },
}
