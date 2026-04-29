# LEGAL NOTICE AND DISCLAIMER

## Radio Frequency Transmission Warning

**THIS SOFTWARE INCLUDES RF TRANSMISSION CAPABILITIES THAT ARE REGULATED BY
FEDERAL, STATE, AND INTERNATIONAL LAW.**

Unauthorized radio transmission is a **federal criminal offense** in the United
States under 47 U.S.C. § 333 (willful interference) and violations of FCC
Part 97 (amateur radio) and Part 15 (unlicensed devices). Penalties include
fines up to **$100,000** and imprisonment up to **one year** per violation.

Similar laws apply internationally, including but not limited to:
- **United Kingdom:** Wireless Telegraphy Act 2006
- **European Union:** Radio Equipment Directive 2014/53/EU
- **Canada:** Radiocommunication Act R.S.C. 1985
- **Australia:** Radiocommunications Act 1992

## Authorized Use Only

This software is designed for:
- **Licensed amateur radio operators** operating within their authorized bands
- **Authorized security researchers** with written permission and Rules of
  Engagement (ROE) from the system owner
- **Authorized training environments** under direct instructor supervision with
  proper shielding or RF-isolated test ranges

TX features are **disabled by default** and require explicit activation. All
transmission attempts are logged to an immutable audit trail.

## No Warranty

THIS SOFTWARE IS PROVIDED "AS IS" WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED. THE AUTHORS AND CONTRIBUTORS ARE NOT RESPONSIBLE FOR ANY DAMAGE,
INTERFERENCE, LEGAL ACTION, OR REGULATORY PENALTY RESULTING FROM USE OR
MISUSE OF THIS SOFTWARE.

## User Responsibility

By using this software, you acknowledge that:

1. You are solely responsible for compliance with all applicable laws and
   regulations in your jurisdiction.
2. You will not transmit on any frequency without proper authorization.
3. You understand that improper RF transmission can interfere with emergency
   services, aviation, and critical infrastructure.
4. You will obtain written ROE approval before enabling TX features in any
   operational or training context.
5. You will not use this software for jamming, spoofing, or any form of
   electronic warfare outside of explicitly authorized training environments.

## RX-Only Default

Recon-Raven operates in **receive-only mode by default**. No RF energy is
transmitted unless the operator explicitly:
1. Enables the TX master switch via API
2. Passes all 5 safety gate checks (frequency whitelist, power cap, duration
   limit, RF amplifier block, audit log)
3. Issues a specific transmit command with valid parameters

## Contact

If you believe this software has been used in violation of any law or regulation,
contact the repository maintainer immediately.
