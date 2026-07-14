from typing import Dict, Any

def normalize_device_platform(vendor: str, platform: str) -> str:
    """
    Ensure vendor and platform are aligned and prevent silent fallback to Cisco
    when the vendor is H3C, Huawei, Ruijie, ZTE, Maipu, DCN, DPtech,
    FiberHome, Juniper, or Arista.
    """
    v = str(vendor or '').strip().lower()
    p = str(platform or '').strip().lower()
    
    # Map vendor names to vendor keys
    if 'huawei' in v or 'vrp' in v:
        v_key = 'huawei'
    elif 'h3c' in v or 'comware' in v or 'hp' in v:
        v_key = 'h3c'
    elif 'ruijie' in v or 'rgos' in v:
        v_key = 'ruijie'
    elif 'zte' in v or 'zxros' in v:
        v_key = 'zte'
    elif 'maipu' in v:
        v_key = 'maipu'
    elif 'juniper' in v or 'junos' in v:
        v_key = 'juniper'
    elif 'arista' in v or 'eos' in v:
        v_key = 'arista'
    elif 'cisco' in v or 'ios' in v:
        v_key = 'cisco'
    else:
        v_key = ''

    # Preserve explicit platform variants for command catalogs and parsers.
    # Generic vendor values still use the historical defaults below.
    explicit_platforms = {
        'huawei_vrp', 'huawei_vrpv8', 'vrp5', 'vrpv5', 'vrp8', 'vrpv8',
        'h3c_comware', 'h3c_comware9', 'hp_comware', 'comware5', 'comware7', 'comware9',
        'ruijie_rgos', 'ruijie_os', 'zte_zxros', 'maipu', 'maipu_network',
    }
    if p in explicit_platforms:
        if p in {'vrp8', 'vrpv8'}:
            return 'huawei_vrpv8'
        if p in {'vrp5', 'vrpv5'}:
            return 'huawei_vrp'
        if p == 'comware5':
            return 'hp_comware'
        if p == 'comware7':
            return 'h3c_comware'
        if p == 'comware9':
            return 'h3c_comware9'
        if p in {'ruijie_os', 'ruijie_rgos'}:
            return 'ruijie_rgos'
        if p == 'maipu_network':
            return 'maipu'
        return p

    # If platform is empty or generic/cisco but vendor is specific, override it
    if v_key == 'huawei':
        if not p or 'cisco' in p or p == 'generic':
            return 'huawei_vrp'
    elif v_key == 'h3c':
        if not p or 'cisco' in p or p == 'generic':
            return 'h3c_comware'
    elif v_key == 'ruijie':
        if not p or 'cisco' in p or p == 'generic':
            return 'ruijie_rgos'
    elif v_key == 'zte':
        if not p or 'cisco' in p or p == 'generic':
            return 'zte_zxros'
    elif v_key == 'maipu':
        if not p or 'cisco' in p or p == 'generic':
            return 'maipu'
    elif v_key == 'juniper':
        if not p or 'cisco' in p or p == 'generic':
            return 'juniper_junos'
    elif v_key == 'arista':
        if not p or 'cisco' in p or p == 'generic':
            return 'arista_eos'

    # Normalization of platform aliases
    if 'huawei' in p or 'vrp' in p:
        return 'huawei_vrp'
    elif 'h3c' in p or 'comware' in p:
        return 'h3c_comware'
    elif 'ruijie' in p or 'rgos' in p:
        return 'ruijie_rgos'
    elif 'zte' in p or 'zxros' in p:
        return 'zte_zxros'
    elif 'maipu' in p:
        return 'maipu'
    elif 'juniper' in p or 'junos' in p:
        return 'juniper_junos'
    elif 'arista' in p or 'eos' in p:
        return 'arista_eos'
    elif 'nxos' in p or 'nexus' in p:
        return 'cisco_nxos'
        
    return platform or 'cisco_ios'
