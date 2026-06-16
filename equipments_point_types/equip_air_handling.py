"""
Equipment definitions for air handling units.

Haystack hierarchy:
    equip → airHandlingEquip → ahu | doas | mau | fcu

Each entry in EQUIPMENT contains:
    point_types  — point-type labels for this subtype; pass to build_tagconditions()
    equip_tags   — Haystack entity-level markers; go in the equipment_tag table
"""

_BASE = [
    'Disc_airtemp',
    'Disc_airtemp-sp',
    'Disc_airflow',
    'Disc_airflow-sp',
    'SF_speed',
    'SF_status',
    'SF_enable-cmd',
    'SF_speed-cmd',
    'HwValve_cmd',
    'HwValve_pos',
    'Zone_occ-heating-sp',
    'Zone_occ-cooling-sp',
    'Zone_unocc-heating-sp',
    'Zone_unocc-cooling-sp',
    'Zone_eff-occup',
]

EQUIPMENT = {

    # Standard recirculating AHU — return, mixed air, OA mixing, fans
    'AHU': {
        'point_types': _BASE + [
            'Ret_airtemp',
            'Mix_airtemp',
            'OA_airtemp',
            'Disc_air-pressure',
            'Disc_air-pressure-sp',
            'OA_damper-cmd',
            'OA_damper-pos',
            'Ret_damper-pos',
            'RF_speed',
            'RF_status',
            'RF_enable-cmd',
            'RF_speed-cmd',
            'ExhF_speed',
            'ExhF_status',
            'ExhF_enable-cmd',
            'ExhF_speed-cmd',
            'HtgValve_cmd',
            'HtgValve_sig',
            'ClgValve_cmd',
            'ClgValve_sig',
            'ChwValve_cmd',
            'ChwValve_pos',
            'HwEnt_watertemp',
            'HwLvg_watertemp',
            'ChwEnt_watertemp',
            'ChwLvg_watertemp',
        ],
        'equip_tags': ['equip', 'airHandlingEquip', 'ahu'],
    },

    # Dedicated Outdoor Air System — 100% OA, no return air stream
    'DOAS': {
        'point_types': _BASE + [
            'OA_airtemp',
            'OA_damper-cmd',
            'OA_damper-pos',
            'Disc_air-pressure',
            'Disc_air-pressure-sp',
            'ChwValve_cmd',
            'ChwValve_pos',
            'ChwEnt_watertemp',
            'ChwLvg_watertemp',
            'OA-Ent_ppm',
            'OA_humidity',
        ],
        'equip_tags': ['equip', 'airHandlingEquip', 'doas'],
    },

    # Makeup Air Unit — 100% OA, heating only (no cooling coil)
    'MAU': {
        'point_types': _BASE + [
            'OA_airtemp',
            'OA_damper-cmd',
            'OA_damper-pos',
            'HtgValve_cmd',
            'HtgValve_sig',
        ],
        'equip_tags': ['equip', 'airHandlingEquip', 'mau'],
    },

    # Fan Coil Unit — room-level, no OA, no return fan, simpler controls
    'FCU': {
        'point_types': _BASE + [
            'Ret_airtemp',
            'Zone_airtemp',
            'ChwValve_cmd',
            'ChwValve_pos',
        ],
        'equip_tags': ['equip', 'airHandlingEquip', 'fcu'],
    },
}
