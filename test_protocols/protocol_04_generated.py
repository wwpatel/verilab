from opentrons import protocol_api

metadata = {"protocolName": "protocol_04", "author": "generated"}
requirements = {"robotType": "Flex", "apiLevel": "2.20"}


def run(protocol: protocol_api.ProtocolContext):
    reservoir_10mL = protocol.load_labware("nest_12_reservoir_15ml", "A1")
    pcr_plate_1 = protocol.load_labware("corning_384_wellplate_112ul_flat", "A2")
    pcr_plate_2 = protocol.load_labware("corning_384_wellplate_112ul_flat", "B1")
    pcr_plate_3 = protocol.load_labware("corning_384_wellplate_112ul_flat", "B2")
    tiprack = protocol.load_labware("opentrons_flex_96_tiprack_50ul", "B3")
    protocol.load_trash_bin("A3")
    pipette = protocol.load_instrument("flex_1channel_50", "left", tip_racks=[tiprack])

    # MANUAL step 0: add 2534 uL of Platinum Hot Start PCR 2X Master Mix to reservoir_10mL:A1 (off-deck reagent, not automated)
    # MANUAL step 1: add 3295 uL of PCR Clean Water to reservoir_10mL:A1 (off-deck reagent, not automated)
    # step 2: mix (vortex/manual, not automated)
    # EXTERNAL step 3: epMotion -- Dispenses 4.6 µL of PCR Master Mix from the 10 mL reservoir into all wells of three 384-well PCR plates using multidispense feature.
    protocol.pause(
        "Manual step: epMotion. Resume when complete."
    )
