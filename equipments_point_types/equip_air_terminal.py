"""
Equipment definitions for air terminal units.

Haystack hierarchy:
    equip → airTerminalUnit → vav | vavReheat | vavElecReheat | fptu | cav

FPTU notes:
    - 'fcu' is NOT used — FCUs are standalone room units, not terminal units.
    - 'fan' is an entity-level marker indicating the integral fan.
    - 'parallel' / 'series' distinguish the two FPTU configurations:
        parallel — fan draws from plenum, runs only when primary air is insufficient (heating mode)
        series   — fan runs continuously, primary air always mixes with plenum return

OA VAV notes:
    - Controls outside/ventilation air only; no recirculated airflow.
    - OA flow and damper points replace Zone airflow and Damper points.
    - Zone_ppm (CO2) drives Demand Controlled Ventilation (DCV).
    - Reheat variants exist where the OA VAV also provides zone heating.

Each entry in EQUIPMENT contains:
    point_types  — point-type labels for this subtype; pass to build_tagconditions()
    equip_tags   — Haystack entity-level markers; go in the equipment_tag table
"""

_BASE = [
    'Zone_airflow',
    'Zone_airflow-sp',
    'Zone_airtemp',
    'Damper_cmd',
    'Damper_pos',
    'Zone_occ-heating-sp',
    'Zone_occ-cooling-sp',
    'Zone_unocc-heating-sp',
    'Zone_unocc-cooling-sp',
    'Zone_eff-occup',
]

_OA_BASE = [
    'OA_airflow',
    'OA_min-airflow-sp',
    'OA_damper-cmd',
    'OA_damper-pos',
    'Zone_airtemp',
    'Zone_ppm',
    'Zone_eff-occup',
]

_EA_BASE = [
    'Exh_airflow',
    'Exh_airflow-sp',
    'Exh_airflow-min-sp',
    'Exh_damper-cmd',
    'Exh_damper-pos',
    'Zone_eff-occup',
]

EQUIPMENT = {

    # Basic VAV — pressure-dependent or pressure-independent, no reheat
    'VAV': {
        'point_types': _BASE,
        'equip_tags': ['equip', 'airTerminalUnit', 'vav'],
    },

    # VAV with hot water reheat coil (most common — e.g. VAVRH)
    'VAV-RH-HW': {
        'point_types': _BASE + [
            'Disc_airtemp',
            'HwValve_cmd',
            'HwValve_pos',
        ],
        'equip_tags': ['equip', 'airTerminalUnit', 'vav', 'hotWaterReheat'],
    },

    # VAV with electric reheat coil
    'VAV-RH-ELEC': {
        'point_types': _BASE + [
            'Disc_airtemp',
            'Coil-elecHeating_stage',
            'Coil-elec_cmd',
        ],
        'equip_tags': ['equip', 'airTerminalUnit', 'vav', 'elecReheat'],
    },

    # Fan-Powered Terminal Unit — parallel, hot water reheat
    # Fan draws from plenum; runs only when primary air is insufficient (heating mode)
    'FPTU-PARALLEL-HW': {
        'point_types': _BASE + [
            'Disc_airtemp',
            'HwValve_cmd',
            'HwValve_pos',
            'SF_speed',
            'SF_status',
            'SF_speed-cmd',
        ],
        'equip_tags': ['equip', 'airTerminalUnit', 'vav', 'fan', 'parallel', 'hotWaterReheat'],
    },

    # Fan-Powered Terminal Unit — series, hot water reheat
    # Fan runs continuously; primary air always mixes with plenum return
    'FPTU-SERIES-HW': {
        'point_types': _BASE + [
            'Disc_airtemp',
            'HwValve_cmd',
            'HwValve_pos',
            'SF_speed',
            'SF_status',
            'SF_speed-cmd',
        ],
        'equip_tags': ['equip', 'airTerminalUnit', 'vav', 'fan', 'series', 'hotWaterReheat'],
    },

    # Fan-Powered Terminal Unit — parallel, electric reheat
    'FPTU-PARALLEL-ELEC': {
        'point_types': _BASE + [
            'Disc_airtemp',
            'Coil-elecHeating_stage',
            'Coil-elec_cmd',
            'SF_speed',
            'SF_status',
            'SF_speed-cmd',
        ],
        'equip_tags': ['equip', 'airTerminalUnit', 'vav', 'fan', 'parallel', 'elecReheat'],
    },

    # Fan-Powered Terminal Unit — series, electric reheat
    'FPTU-SERIES-ELEC': {
        'point_types': _BASE + [
            'Disc_airtemp',
            'Coil-elecHeating_stage',
            'Coil-elec_cmd',
            'SF_speed',
            'SF_status',
            'SF_speed-cmd',
        ],
        'equip_tags': ['equip', 'airTerminalUnit', 'vav', 'fan', 'series', 'elecReheat'],
    },

    # Outside Air VAV — ventilation only, no reheat
    'OAVAV': {
        'point_types': _OA_BASE,
        'equip_tags': ['equip', 'airTerminalUnit', 'vav', 'outside'],
    },

    # Outside Air VAV — with hot water reheat
    'OAVAV-RH-HW': {
        'point_types': _OA_BASE + [
            'Disc_airtemp',
            'HwValve_cmd',
            'HwValve_pos',
            'Zone_occ-heating-sp',
            'Zone_unocc-heating-sp',
        ],
        'equip_tags': ['equip', 'airTerminalUnit', 'vav', 'outside', 'hotWaterReheat'],
    },

    # Outside Air VAV — with electric reheat
    'OAVAV-RH-ELEC': {
        'point_types': _OA_BASE + [
            'Disc_airtemp',
            'Coil-elecHeating_stage',
            'Coil-elec_cmd',
            'Zone_occ-heating-sp',
            'Zone_unocc-heating-sp',
        ],
        'equip_tags': ['equip', 'airTerminalUnit', 'vav', 'outside', 'elecReheat'],
    },

    # Exhaust Air VAV — modulates exhaust air from a zone; paired with OA VAV for pressurization
    'EAVAV': {
        'point_types': _EA_BASE,
        'equip_tags': ['equip', 'airTerminalUnit', 'vav', 'exhaust'],
    },
}
