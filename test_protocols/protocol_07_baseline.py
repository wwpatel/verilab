from opentrons import protocol_api

metadata = {
    "protocolName": "DNA Extraction - Washing and Hydration Steps (Steps 22-26)",
    "author": "Lab Automation",
    "description": "Blood clot preparation, RBC lysis, WBC lysis, protein precipitation, DNA precipitation, DNA washing, and DNA hydration - Steps 22-26: DNA washing with 70% ethanol, air drying, hydration, and transfer.",
    "apiLevel": "2.20"
}

requirements = {"robotType": "Flex"}

def run(protocol: protocol_api.ProtocolContext):

    # ── Labware ──────────────────────────────────────────────────────────────
    # 50 mL tube rack for source tubes (ethanol, hydration solution)
    reagent_rack = protocol.load_labware(
        "opentrons_6_tuberack_falcon_50ml_conical",
        location="D1",
        label="Reagent Rack (50 mL tubes)"
    )

    # 15 mL / 50 mL tube rack for sample tubes
    sample_rack_50ml = protocol.load_labware(
        "opentrons_6_tuberack_falcon_50ml_conical",
        location="D2",
        label="Sample Rack (50 mL tubes)"
    )

    # 2 mL tube rack for final storage tubes
    storage_rack = protocol.load_labware(
        "opentrons_24_tuberack_eppendorf_2ml_safelock_snapcap",
        location="D3",
        label="Storage Rack (2 mL tubes)"
    )

    # Tip racks
    tiprack_1000_1 = protocol.load_labware(
        "opentrons_flex_96_tiprack_1000ul",
        location="B1",
        label="1000 uL Tips 1"
    )
    tiprack_1000_2 = protocol.load_labware(
        "opentrons_flex_96_tiprack_1000ul",
        location="B2",
        label="1000 uL Tips 2"
    )
    tiprack_200_1 = protocol.load_labware(
        "opentrons_flex_96_tiprack_200ul",
        location="B3",
        label="200 uL Tips 1"
    )

    # Temperature module for 65°C incubation (hydration step)
    temp_module = protocol.load_module(
        "temperatureModuleV2",
        location="C1"
    )
    temp_plate = temp_module.load_labware(
        "opentrons_24_aluminumblock_nest_1.5ml_snapcap",
        label="Temp Block for Hydration"
    )

    # ── Pipettes ─────────────────────────────────────────────────────────────
    p1000 = protocol.load_instrument(
        "flex_1channel_1000",
        mount="left",
        tip_racks=[tiprack_1000_1, tiprack_1000_2]
    )
    p200 = protocol.load_instrument(
        "flex_1channel_50",
        mount="right",
        tip_racks=[tiprack_200_1]
    )

    # ── Reagent Positions ────────────────────────────────────────────────────
    # 70% ethanol in 50 mL tube - reagent_rack A1
    ethanol_70 = reagent_rack["A1"]

    # DNA Hydration Solution (Qiagen) in 50 mL tube - reagent_rack A2
    hydration_solution = reagent_rack["A2"]

    # ── Sample Positions ────────────────────────────────────────────────────
    # Up to 6 sample tubes in 50 mL conical tubes (post DNA precipitation)
    # Samples are assumed to be in sample_rack_50ml positions A1-B3
    sample_tubes = [
        sample_rack_50ml["A1"],
        sample_rack_50ml["A2"],
        sample_rack_50ml["A3"],
        sample_rack_50ml["B1"],
        sample_rack_50ml["B2"],
        sample_rack_50ml["B3"],
    ]

    # 2 mL storage tubes corresponding to each sample
    storage_tubes = [
        storage_rack["A1"],
        storage_rack["A2"],
        storage_rack["A3"],
        storage_rack["A4"],
        storage_rack["A5"],
        storage_rack["A6"],
    ]

    # Number of samples to process
    num_samples = 6

    # Volume of hydration solution (uL):
    # 500 uL for large pellet, 300 uL for smaller pellet
    # Using 500 uL as default for large pellet
    hydration_volume_large = 500   # uL
    hydration_volume_small = 300   # uL

    # Assign volumes per sample (modify as needed: True = large pellet)
    large_pellet_flags = [True, True, True, True, True, True]

    # ── Step 22: Supernatant discarded (manual step) ─────────────────────────
    # NOTE: Centrifugation at 2000 x g for 3 min and supernatant removal
    # is performed manually before this protocol starts.
    # The pellet should be in the tube with tube drained on absorbent paper.
    protocol.comment(
        "MANUAL STEP - Step 22: Ensure centrifugation at 2000 x g for 3 min "
        "has been completed. Supernatant has been carefully discarded and tubes "
        "drained on absorbent paper. DNA pellet remains in tube. "
        "Resume protocol when ready."
    )
    protocol.pause(
        "Step 22 complete? Confirm supernatant discarded and tubes drained. "
        "Press Resume to continue with Step 23 (70% ethanol wash)."
    )

    # ── Step 23: Add 5 mL 70% ethanol and invert to detach pellet ────────────
    protocol.comment("Step 23: Adding 5 mL of 70% ethanol to each sample tube.")

    for i in range(num_samples):
        protocol.comment(f"  Adding 70% ethanol to sample {i+1}...")
        p1000.pick_up_tip()
        # Add 5 mL (5 x 1000 uL transfers)
        for _ in range(5):
            p1000.aspirate(1000, ethanol_70)
            p1000.dispense(1000, sample_tubes[i].top(-5))
        p1000.drop_tip()

    protocol.comment(
        "MANUAL STEP - Step 23 (continued): Invert each tube until the pellet "
        "is detached from the tube wall. Ensure thorough mixing."
    )
    protocol.pause(
        "Please invert all tubes until the pellet is detached. "
        "Press Resume when done to proceed to centrifugation."
    )

    # ── Step 24: Centrifugation, supernatant removal, air drying ─────────────
    protocol.comment(
        "MANUAL STEP - Step 24: Centrifuge all tubes at 2000 x g for 3 min. "
        "After centrifugation, carefully discard supernatant. "
        "Air dry the DNA pellet at room temperature for 10 min or until glassy."
    )
    protocol.pause(
        "Step 24: Complete centrifugation (2000 x g, 3 min), discard supernatant, "
        "and air dry pellet for ~10 min at room temperature until glassy. "
        "Press Resume when air drying is complete."
    )

    # ── Step 25: Add DNA Hydration Solution and incubate at 65°C ─────────────
    protocol.comment("Step 25: Setting temperature module to 65°C for hydration.")
    temp_module.set_temperature(65)
    protocol.comment("Waiting for temperature module to reach 65°C...")
    temp_module.await_temperature(65)
    protocol.comment("Temperature module reached 65°C.")

    protocol.comment("Step 25: Adding DNA Hydration Solution to each sample.")

    for i in range(num_samples):
        hydration_vol = hydration_volume_large if large_pellet_flags[i] else hydration_volume_small
        protocol.comment(
            f"  Sample {i+1}: Adding {hydration_vol} uL DNA Hydration Solution "
            f"({'large' if large_pellet_flags[i] else 'small'} pellet)."
        )
        p1000.pick_up_tip()
        p1000.aspirate(hydration_vol, hydration_solution)
        # Dispense directly to the 50 mL sample tube
        p1000.dispense(hydration_vol, sample_tubes[i].top(-10))
        p1000.mix(3, min(hydration_vol, 1000), sample_tubes[i].bottom(5))
        p1000.blow_out(sample_tubes[i].top(-5))
        p1000.drop_tip()

    protocol.comment(
        "MANUAL STEP - Step 25 (Incubation): Transfer sample tubes to a warming "
        "cabinet set at 65°C and incubate for 1 hour. "
        "After incubation, place samples on a shaker at room temperature overnight "
        "to fully dissolve the DNA."
    )
    protocol.pause(
        "Step 25: Transfer sample tubes to 65°C warming cabinet for 1 hour, "
        "then shaker overnight at room temperature. "
        "Return tubes to the deck and press Resume when DNA is fully dissolved."
    )

    # Turn off temperature module after incubation
    temp_module.deactivate()

    # ── Step 26: Brief centrifugation and transfer to 2 mL storage tubes ─────
    protocol.comment(
        "MANUAL STEP - Step 26 (Centrifugation): Briefly centrifuge all sample "
        "tubes to pellet any undissolved material before transferring."
    )
    protocol.pause(
        "Step 26: Briefly centrifuge all sample tubes. "
        "Press Resume to proceed with transfer of dissolved DNA to 2 mL storage tubes."
    )

    protocol.comment("Step 26: Transferring dissolved DNA to 2 mL storage tubes.")

    for i in range(num_samples):
        hydration_vol = hydration_volume_large if large_pellet_flags[i] else hydration_volume_small
        protocol.comment(f"  Transferring dissolved DNA from sample {i+1} to storage tube {i+1}...")

        p1000.pick_up_tip()
        # Aspirate dissolved DNA carefully from the bottom of the 50 mL tube
        # avoiding any remaining pellet
        p1000.aspirate(
            hydration_vol,
            sample_tubes[i].bottom(10),
            rate=0.3  # slow aspiration to avoid disturbing pellet
        )
        protocol.delay(seconds=2)  # allow liquid to settle into tip
        p1000.dispense(hydration_vol, storage_tubes[i])
        p1000.blow_out(storage_tubes[i].top(-2))
        p1000.drop_tip()
        protocol.comment(f"  Sample {i+1} transferred to storage tube {i+1}.")

    protocol.comment(
        "MANUAL STEP - Step 26 (Storage): Transfer 2 mL storage tubes to -20°C freezer."
    )
    protocol.pause(
        "Step 26 complete: Please transfer all 2 mL storage tubes to -20°C for storage. "
        "Protocol finished."
    )

    protocol.comment(
        "Protocol complete. DNA has been washed with 70% ethanol, air-dried, "
        "hydrated, and transferred to 2 mL storage tubes for -20°C storage."
    )