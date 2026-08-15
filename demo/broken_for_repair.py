from opentrons import protocol_api

metadata = {"protocolName": "Repair Loop Demo"}
requirements = {"robotType": "Flex", "apiLevel": "2.20"}


def run(protocol: protocol_api.ProtocolContext):
    plate = protocol.load_labware("corning_96_wellplate_360ul_flat", "C1")
    reservoir = protocol.load_labware("nest_12_reservoir_15ml", "C2")
    tiprack = protocol.load_labware("opentrons_flex_96_tiprack_1000ul", "C3")
    trash = protocol.load_trash_bin("A3")
    pipette = protocol.load_instrument("flex_1channel_1000", "left", tip_racks=[tiprack])

    pipette.transfer(200, reservoir["A1"], plate["A1"])