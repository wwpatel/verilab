from opentrons import protocol_api

metadata = {"protocolName": "protocol_07", "author": "generated"}
requirements = {"robotType": "Flex", "apiLevel": "2.20"}


def run(protocol: protocol_api.ProtocolContext):
    tube_1 = protocol.load_labware("opentrons_24_tuberack_generic_2ml_screwcap", "A1")
    tube_2 = protocol.load_labware("opentrons_24_tuberack_generic_2ml_screwcap", "A2")
    tiprack = protocol.load_labware("opentrons_flex_96_tiprack_50ul", "B1")
    protocol.load_trash_bin("A3")
    pipette = protocol.load_instrument("flex_1channel_50", "left", tip_racks=[tiprack])

    # EXTERNAL step 0: centrifuge -- Centrifuge tube at 2000 x g for 3 minutes to pellet DNA.
    protocol.pause(
        "Manual step: centrifuge. Resume when complete."
    )
    # SKIPPED step 1: missing volume or destination
    # MANUAL step 2: add 5000 uL of 70% ethanol to tube_1:pellet (off-deck reagent, not automated)
    # EXTERNAL step 3: centrifuge -- Centrifuge tube at 2000 x g for 3 minutes.
    protocol.pause(
        "Manual step: centrifuge. Resume when complete."
    )
    # SKIPPED step 4: missing volume or destination
    protocol.delay(seconds=600)
    # SKIPPED step 6: missing volume or destination
    protocol.delay(seconds=3600)
    # EXTERNAL step 8: shaker -- Shake sample overnight at room temperature to fully dissolve DNA.
    protocol.pause(
        "Manual step: shaker. Resume when complete."
    )
    # EXTERNAL step 9: centrifuge -- Centrifuge tube briefly.
    protocol.pause(
        "Manual step: centrifuge. Resume when complete."
    )
    # SKIPPED step 10: missing volume or destination
    # step 11: incubate with unspecified duration
