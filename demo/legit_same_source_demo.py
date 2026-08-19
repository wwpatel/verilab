from opentrons import protocol_api

metadata = {"protocolName": "Legitimate Same-Source Reuse Demo"}
requirements = {"robotType": "Flex", "apiLevel": "2.20"}


def run(protocol: protocol_api.ProtocolContext):
    tiprack = protocol.load_labware("opentrons_flex_96_tiprack_1000ul", "A1")
    protocol.load_trash_bin("A3")
    reservoir = protocol.load_labware("nest_12_reservoir_15ml", "B1")
    plate = protocol.load_labware("corning_96_wellplate_360ul_flat", "C1")
    pipette = protocol.load_instrument("flex_1channel_1000", "left", tip_racks=[tiprack])

    # one tip distributing the SAME source to multiple destination wells,
    # never dropped in between. This is normal bench practice (one reservoir
    # feeding many wells of the same reagent) and must not be flagged as
    # contamination, since the tip only ever touches one physical source.
    pipette.pick_up_tip()
    pipette.aspirate(50, reservoir["A1"])
    pipette.dispense(50, plate["A1"])
    pipette.aspirate(50, reservoir["A1"])
    pipette.dispense(50, plate["A2"])
    pipette.aspirate(50, reservoir["A1"])
    pipette.dispense(50, plate["A3"])
    pipette.drop_tip()
