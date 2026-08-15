from opentrons import protocol_api

metadata = {
    "protocolName": "Fungal Spore Growth Curve Plate Preparation",
    "author": "Lab Automation",
    "description": (
        "Dispense spore stock into 96-well plate wells and fill inter-well spaces "
        "with media/H2O to prevent edge effects."
    ),
    "apiLevel": "2.20",
}

requirements = {"robotType": "Flex", "apiLevel": "2.20"}


def run(protocol: protocol_api.ProtocolContext):

    # -------------------------------------------------------------------------
    # CONFIGURABLE PARAMETERS
    # -------------------------------------------------------------------------
    SPORE_STOCK_VOLUME_UL = 5          # uL of spore stock per well
    MEDIA_OVERLAY_VOLUME_UL = 195      # uL of liquid media per well (total 200 uL)
    SPORE_STOCK_WELL = "A1"            # source well for spore stock on reservoir
    MEDIA_STOCK_WELL = "A2"            # source well for liquid media on reservoir

    # Wells to fill with spores (all 96 inner + edge wells = full plate)
    # We define the 96 assay wells (columns 1-12, rows A-H)
    ASSAY_WELLS = [
        f"{row}{col}"
        for col in range(1, 13)
        for row in "ABCDEFGH"
    ]

    # -------------------------------------------------------------------------
    # DECK LAYOUT
    # -------------------------------------------------------------------------
    # Slot D1 : Opentrons Flex 96-well reservoir (or equivalent 12-channel)
    # Slot D2 : CytoOne 96-well flat-bottom plate (target plate)
    # Slot C1 : 50 uL filter tip rack  (for spore aliquoting)
    # Slot C2 : 200 uL filter tip rack (for media dispensing)
    # Slot B1 : 200 uL filter tip rack (extra tips for media if needed)

    tip_rack_50 = protocol.load_labware(
        "opentrons_flex_96_filtertiprack_50uL", "C1"
    )
    tip_rack_200_1 = protocol.load_labware(
        "opentrons_flex_96_filtertiprack_200uL", "C2"
    )
    tip_rack_200_2 = protocol.load_labware(
        "opentrons_flex_96_filtertiprack_200uL", "B1"
    )

    reservoir = protocol.load_labware(
        "nest_12_reservoir_15ml", "D1"
    )

    target_plate = protocol.load_labware(
        "corning_96_wellplate_360ul_flat", "D2"
    )

    # -------------------------------------------------------------------------
    # PIPETTES
    # -------------------------------------------------------------------------
    # Single-channel 50 uL pipette for precise spore aliquoting
    p50 = protocol.load_instrument(
        "flex_1channel_50", "right", tip_racks=[tip_rack_50]
    )

    # Single-channel 1000 uL pipette for media dispensing
    p1000 = protocol.load_instrument(
        "flex_1channel_1000", "left", tip_racks=[tip_rack_200_1, tip_rack_200_2]
    )

    # -------------------------------------------------------------------------
    # STEP 1 – Aliquot 5 uL spore stock into each of the 96 assay wells
    # -------------------------------------------------------------------------
    protocol.comment(
        "Step 1: Aliquoting 5 uL spore stock (4e5 spores/mL in PBS+0.01% Tween) "
        "into each assay well. This delivers ~2000 spores per well."
    )

    spore_source = reservoir[SPORE_STOCK_WELL]

    # Use a single tip for the entire spore dispensing step to conserve tips
    # (vortex/mix is assumed to have been done before loading the reservoir).
    p50.pick_up_tip()
    for well in ASSAY_WELLS:
        p50.aspirate(SPORE_STOCK_VOLUME_UL, spore_source)
        p50.dispense(SPORE_STOCK_VOLUME_UL, target_plate[well])
        p50.touch_tip(target_plate[well])
    p50.drop_tip()

    # -------------------------------------------------------------------------
    # STEP 2 – Overlay each well with 195 uL liquid media (total volume 200 uL)
    # -------------------------------------------------------------------------
    protocol.comment(
        "Step 2: Overlaying each assay well with 195 uL of liquid media "
        "to bring total volume to 200 uL per well."
    )

    media_source = reservoir[MEDIA_STOCK_WELL]

    # Dispense media; change tip between groups of wells to avoid cross-
    # contamination from spore splash-back. Here we use one tip per column
    # as a practical compromise (change as needed).
    for col_idx in range(1, 13):
        p1000.pick_up_tip()
        for row in "ABCDEFGH":
            well_name = f"{row}{col_idx}"
            p1000.aspirate(MEDIA_OVERLAY_VOLUME_UL, media_source)
            # Dispense slowly above the liquid surface to avoid disturbing spores
            p1000.dispense(
                MEDIA_OVERLAY_VOLUME_UL,
                target_plate[well_name].top(-2),
                rate=0.5,
            )
            p1000.blow_out(target_plate[well_name].top(-2))
        p1000.drop_tip()

    # -------------------------------------------------------------------------
    # STEP 3 – Fill inter-well spaces with media to prevent edge effect
    # -------------------------------------------------------------------------
    # The CytoOne plate has a standard SBS footprint; the "space between wells"
    # refers to the moat / reservoir area around the 96-well array.
    # We simulate this by dispensing media into a waste/moat labware if
    # available, or by noting that this step must be done manually for sealed
    # SBS plates that have no accessible moat.
    #
    # If the plate has an accessible moat (some plates have a peripheral trough),
    # the block below dispenses media into it.  Adjust well names / labware as
    # required.  For standard CytoOne plates without a moat, this step is manual.

    protocol.comment(
        "Step 3: NOTE – Filling the space between the well array and the plate "
        "edge with media or H2O to prevent edge effects. "
        "For CytoOne plates this is typically done manually after robot transfer. "
        "If your plate has a peripheral moat, update this section with the "
        "correct labware and well coordinates."
    )

    # Example placeholder for plates with a moat – uncomment and adapt:
    # MOAT_VOLUME_UL = 1000
    # moat_wells = ["A1", "A2"]   # replace with actual moat well names
    # p1000.pick_up_tip()
    # for mw in moat_wells:
    #     p1000.aspirate(MOAT_VOLUME_UL, media_source)
    #     p1000.dispense(MOAT_VOLUME_UL, moat_labware[mw])
    # p1000.drop_tip()

    # -------------------------------------------------------------------------
    # STEP 4 – Protocol complete; remind user of downstream steps
    # -------------------------------------------------------------------------
    protocol.comment(
        "Plate preparation complete.\n"
        "Next steps (manual):\n"
        "  1. Cover the 96-well plate with a breathable membrane.\n"
        "  2. Load the plate into the plate reader (Powerwave X-2 / BioTek).\n"
        "  3. Pre-heat reader to 37 °C and take a blank OD600 reading.\n"
        "  4. Run kinetic OD600 measurements every 10 min for 48 h.\n"
        "     Instrument settings: wavelength = 600 nm, interval = 10 min, "
        "duration = 48:00:00, temperature = 37 °C."
    )