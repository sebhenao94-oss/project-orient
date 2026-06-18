"""
Equipment definitions for ventilation equipment.

Haystack hierarchy:
    equip → airHandlingEquip (ERV, HRV)

Each entry in EQUIPMENT contains:
    point_types  — point-type labels for this subtype; pass to build_tagconditions()
    equip_tags   — Haystack entity-level markers; go in the equipment_tag table
"""

EQUIPMENT = {

    # Energy Recovery Ventilator — heat wheel, OA intake + exhaust-side points
    'ERV': {
        'point_types': [
            'OA_airtemp',
            'OA_humidity',
            'OA_airflow',
            'OA_damper-cmd',
            'OA_damper-pos',
            'OA-Ent_ppm',
            'OA-Lvg_ppm',
            'OA_min-airflow-sp',
            'OA_min-damper-pos-sp',
            'OA_heat-status',
            'OA-Ent_airtemp',
            'OA-Lvg_airtemp',
            'OA-Lvg_humidity',
            'OA-Lvg_enthalpy',
            'Heatwheel_cmd',
            'Heatwheel_run',
        ],
        'equip_tags': ['equip', 'airHandlingEquip', 'erv', 'energyRecovery'],
    },
}
