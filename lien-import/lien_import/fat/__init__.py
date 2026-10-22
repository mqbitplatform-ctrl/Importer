"""Free America Tax lien-pull automation (handoff section 16).

Selects liens from the consolidated `liens` table (all sources: LN + TN + ES)
matching the FAT criteria and records each pull in zm_dba's existing
`liens_custom_data` table (user_index 61379, 'FREEAMTAX Case ID'), the same
way the current manual process does, so a lien is never pulled twice. Writes
the pull as a CSV for the mail job.
"""
