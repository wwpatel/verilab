from opentrons import protocol_api

metadata = {
    "protocolName": "PCR Master Mix Preparation and Plate Setup for 100 Samples",
    "author": "Opentrons",
    "description": (
        "Prepares PCR Master Mix in a 15 mL Falcon tube and distributes to a 96-well "
        "plate, then adds DNA samples. Steps 3 (SYBR dilution), 8 (vortex/spin), "
        "11 (thaw/spin), 13 (seal), and 14 (BioRad run) require manual intervention."
    ),
}

requirements = {"robotType": "Flex", "apiLevel": "2.20"}


def run(protocol: protocol_api.ProtocolContext):

    # ── Deck layout ────────────────────────────────────────────────────────────
    # Slot A1 – 50 mL tube rack (holds 15 mL Falcon with master mix)
    # Slot A2 – 15 mL tube rack (holds SYBR 1:100 dilution tube + PCR water aliquot)
    # Slot B1 – Reagent reservoir / tube rack for reagents
    # Slot C1 – 96-well PCR plate (green destination plate)
    # Slot D1 – 96-well plate with extracted DNA samples
    # Slot A3 – 200 µL tip rack
    # Slot B3 – 200 µL tip rack (extra)
    # Slot C3 – 1000 µL tip rack
    # Slot D3 – 1000 µL tip rack (extra)
    # Slot B2 – Trash / waste (built-in)

    # Labware
    falcon_rack = protocol.load_labware(
        "opentrons_10_tuberack_falcon_4x50ml_6x15ml_conical", "A1"
    )
    small_tube_rack = protocol.load_labware(
        "opentrons_24_tuberack_eppendorf_1.5ml_safelock_snapcap", "A2"
    )
    reagent_rack = protocol.load_labware(
        "opentrons_10_tuberack_falcon_4x50ml_6x15ml_conical", "B1"
    )
    dest_plate = protocol.load_labware(
        "opentrons_96_wellplate_200ul_pcr_full_skirt", "C1"
    )
    dna_plate = protocol.load_labware(
        "opentrons_96_wellplate_200ul_pcr_full_skirt", "D1"
    )

    # Tip racks
    tiprack_200_1 = protocol.load_labware("opentrons_flex_96_tiprack_200ul", "A3")
    tiprack_200_2 = protocol.load_labware("opentrons_flex_96_tiprack_200ul", "B3")
    tiprack_1000_1 = protocol.load_labware("opentrons_flex_96_tiprack_1000ul", "C3")
    tiprack_1000_2 = protocol.load_labware("opentrons_flex_96_tiprack_1000ul", "D3")

    # Pipettes
    p1000 = protocol.load_instrument(
        "flex_1channel_1000",
        mount="left",
        tip_racks=[tiprack_1000_1, tiprack_1000_2],
    )
    p50 = protocol.load_instrument(
        "flex_1channel_50",
        mount="right",
        tip_racks=[tiprack_200_1, tiprack_200_2],
    )

    # ── Tube / well assignments ────────────────────────────────────────────────
    # 15 mL Falcon tube in position A1 of falcon_rack (row 0, col 0 = A1 slot)
    master_mix_tube = falcon_rack["A3"]  # 15 mL position

    # Reagent tubes in reagent_rack (15 mL slots)
    pcr_water_tube = reagent_rack["A3"]   # PCR Water (nuclease free)
    sybr_stock_tube = reagent_rack["A4"]  # SYBR Green stock
    primer1_tube = reagent_rack["B3"]     # Primer 1: GOH-279-M13 10 µM
    primer2_tube = reagent_rack["B4"]     # Primer 2: GOH-280-M13 10 µM
    mix5_tube = reagent_rack["A1"]        # 5× mix (50 mL position)

    # Small tube for SYBR 1:100 dilution (1.5 mL Eppendorf)
    sybr_dilution_tube = small_tube_rack["A1"]
    sybr_water_tube = small_tube_rack["A2"]  # extra PCR water for SYBR dilution

    # ── STEP 1: Pause – label Falcon tube ─────────────────────────────────────
    protocol.pause(
        "MANUAL STEP: Label a new 15 mL Falcon tube as 'PCR Master Mix' and place it "
        "in position A3 of the 50/15 mL tube rack on slot A1. Press Resume when ready."
    )

    # ── STEP 2: Add 850 µL PCR Water to Falcon tube ───────────────────────────
    protocol.comment("Step 2: Adding 850 µL PCR Water to Falcon tube.")
    p1000.pick_up_tip()
    p1000.aspirate(850, pcr_water_tube)
    p1000.dispense(850, master_mix_tube)
    p1000.blow_out(master_mix_tube.top(-5))
    p1000.drop_tip()

    # ── STEP 3: Manual SYBR 1:100 dilution ────────────────────────────────────
    # The robot pre-loads water into the dilution tube; SYBR pipetting can be
    # done robotically, but vortex/spin requires manual intervention.
    protocol.comment(
        "Step 3a: Transferring 297 µL PCR water to SYBR dilution tube."
    )
    p50.pick_up_tip()
    # Transfer 297 µL water to dilution tube using multiple aspirations (50 µL max)
    for _ in range(5):
        p50.aspirate(50, sybr_water_tube)
        p50.dispense(50, sybr_dilution_tube)
    p50.aspirate(47, sybr_water_tube)
    p50.dispense(47, sybr_dilution_tube)
    p50.drop_tip()

    protocol.comment("Step 3b: Adding 3 µL SYBR Green stock to dilution tube.")
    p50.pick_up_tip()
    p50.aspirate(3, sybr_stock_tube)
    p50.dispense(3, sybr_dilution_tube)
    p50.blow_out(sybr_dilution_tube.top(-2))
    p50.drop_tip()

    protocol.pause(
        "MANUAL STEP: Vortex and spin down the SYBR 1:100 dilution tube (slot A2, "
        "position A1). Press Resume when done."
    )

    # ── STEP 4: Add 250 µL SYBR 1:100 dilution to Falcon tube ────────────────
    protocol.comment("Step 4: Adding 250 µL SYBR 1:100 dilution to Falcon tube.")
    p50.pick_up_tip()
    for _ in range(5):
        p50.aspirate(50, sybr_dilution_tube)
        p50.dispense(50, master_mix_tube)
    p50.drop_tip()

    # ── STEP 5: Add 100 µL Primer 1 to Falcon tube ────────────────────────────
    protocol.comment("Step 5: Adding 100 µL Primer 1 (GOH-279-M13) to Falcon tube.")
    p50.pick_up_tip()
    for _ in range(2):
        p50.aspirate(50, primer1_tube)
        p50.dispense(50, master_mix_tube)
    p50.blow_out(master_mix_tube.top(-5))
    p50.drop_tip()

    # ── STEP 6: Add 100 µL Primer 2 to Falcon tube ────────────────────────────
    protocol.comment("Step 6: Adding 100 µL Primer 2 (GOH-280-M13) to Falcon tube.")
    p50.pick_up_tip()
    for _ in range(2):
        p50.aspirate(50, primer2_tube)
        p50.dispense(50, master_mix_tube)
    p50.blow_out(master_mix_tube.top(-5))
    p50.drop_tip()

    # ── STEP 7: Add 1000 µL 5× mix to Falcon tube ────────────────────────────
    protocol.comment("Step 7: Adding 1000 µL 5× mix to Falcon tube.")
    p1000.pick_up_tip()
    p1000.aspirate(1000, mix5_tube)
    p1000.dispense(1000, master_mix_tube)
    p1000.blow_out(master_mix_tube.top(-5))
    p1000.drop_tip()

    # ── STEP 8: Manual vortex and spin down Falcon tube ───────────────────────
    protocol.pause(
        "MANUAL STEP: Remove the Master Mix Falcon tube, quick vortex and spin down. "
        "Return it to position A3 of the tube rack on slot A1. Press Resume."
    )

    # ── STEP 9: Label green 96-well PCR plate ─────────────────────────────────
    protocol.pause(
        "MANUAL STEP: Confirm the green 96-well PCR plate on slot C1 is labeled and "
        "properly seated. Press Resume."
    )

    # ── STEP 10: Add 23 µL Master Mix to each of 100 wells ───────────────────
    # 100 samples → wells A1–D4 of a column-ordered 96-well plate
    # We fill the first 100 wells (columns 1-11 full + 4 wells of column 12)
    protocol.comment("Step 10: Distributing 23 µL Master Mix to 100 wells.")

    all_wells = dest_plate.wells()[:100]

    p50.pick_up_tip()
    for well in all_wells:
        p50.aspirate(23, master_mix_tube)
        p50.dispense(23, well)
        p50.blow_out(well.top(-1))
    p50.drop_tip()

    # ── STEP 11: Manual – thaw and spin down DNA sample plate ─────────────────
    protocol.pause(
        "MANUAL STEP: Thaw and spin down the plate with extracted DNA samples. "
        "Place it on slot D1. Press Resume when ready."
    )

    # ── STEP 12: Add 2 µL DNA to corresponding wells ──────────────────────────
    protocol.comment("Step 12: Adding 2 µL DNA from each sample to Master Mix plate.")

    dna_wells = dna_plate.wells()[:100]

    for src_well, dest_well in zip(dna_wells, all_wells):
        p50.pick_up_tip()
        p50.aspirate(2, src_well)
        p50.dispense(2, dest_well)
        p50.mix(3, 10, dest_well)
        p50.blow_out(dest_well.top(-1))
        p50.drop_tip()

    # ── STEP 13: Manual – seal and spin PCR plate ─────────────────────────────
    protocol.pause(
        "MANUAL STEP: Seal the PCR plate with plastic film and spin down. "
        "Press Resume when done."
    )

    # ── STEP 14: Manual – run on BioRad CFX ──────────────────────────────────
    protocol.pause(
        "MANUAL STEP: Transfer the sealed PCR plate to BioRad CFX. "
        "Run the 'hsp60 qPCR 25 µL 40 cycle' program. Protocol complete."
    )

    protocol.comment("Protocol finished. All automated steps are complete.")