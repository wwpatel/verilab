from opentrons import protocol_api

metadata = {"protocolName": "Tip Contamination Demo"}
requirements = {"robotType": "Flex", "apiLevel": "2.20"}


def run(protocol: protocol_api.ProtocolContext):
    tiprack = protocol.load_labware("opentrons_flex_96_tiprack_1000ul", "A1")
    protocol.load_trash_bin("A3")
    plate = protocol.load_labware("opentrons_96_wellplate_200ul_pcr_full_skirt", "C1")
    pipette = protocol.load_instrument("flex_1channel_1000", "left", tip_racks=[tiprack])

    # deliberately contaminated: one tip touches two different wells,
    # A1 (well A) then A2 (well B), with no drop_tip in between
    pipette.pick_up_tip()
    pipette.aspirate(50, plate["A1"])
    pipette.dispense(50, plate["B1"])
    pipette.aspirate(50, plate["A2"])
    pipette.dispense(50, plate["B2"])
    pipette.drop_tip()
