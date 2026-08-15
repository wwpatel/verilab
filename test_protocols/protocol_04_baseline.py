import math
from opentrons import protocol_api

metadata = {
    "protocolName": "PCR Master Mix Distribution to 384-well Plates",
    "author": "Converted Protocol",
    "description": (
        "Transfers 4.6 uL of PCR Master Mix into three 384-well PCR plates "
        "using multi-dispense from a 10 mL reservoir."
    ),
    "apiLevel": "2.20",
}

NUM_384_PLATES = 3
MASTERMIX_VOL_PER_WELL = 4.6
TOTAL_WELLS_PER_PLATE = 384

# Tip capacity for 50 uL tips; leave headroom for multi-dispense
TIP_MAX_VOLUME = 50
DISPENSE_HEADROOM = 2.0  # dead / blow-out volume per aspirate cycle
WELLS_PER_ASPIRATE = math.floor(
    (TIP_MAX_VOLUME - DISPENSE_HEADROOM) / MASTERMIX_VOL_PER_WELL
)  # how many wells we can fill per tip pickup


def run(protocol: protocol_api.ProtocolContext):

    # ------------------------------------------------------------------ #
    # Labware                                                              #
    # ------------------------------------------------------------------ #

    # Tips: 1-50 uL filtered tips on slot A4
    tiprack = protocol.load_labware(
        "opentrons_flex_96_tiprack_50ul",
        location="A4",
        label="50 uL Filter Tips",
    )

    # Three empty 384-well PCR plates on B1, B2, B3
    pcr_plates = []
    for slot, label_num in zip(["B1", "B2", "B3"], [1, 2, 3]):
        plate = protocol.load_labware(
            "corning_384_wellplate_112ul_flat",
            location=slot,
            label=f"384-well PCR Plate {label_num}",
        )
        pcr_plates.append(plate)

    # 10 mL reservoir on slot B4 (using a 12-column reservoir; first well holds master mix)
    reservoir = protocol.load_labware(
        "nest_12_reservoir_15ml",
        location="B4",
        label="PCR Master Mix Reservoir",
    )
    mastermix_well = reservoir["A1"]

    # ------------------------------------------------------------------ #
    # Pipette                                                              #
    # ------------------------------------------------------------------ #
    # Single-channel 50 uL pipette on left mount
    pipette = protocol.load_instrument(
        "flex_1channel_50",
        mount="left",
        tip_racks=[tiprack],
    )

    # ------------------------------------------------------------------ #
    # Helper: multi-dispense into a list of destination wells             #
    # ------------------------------------------------------------------ #
    def multi_dispense_to_wells(dest_wells):
        """
        Aspirate enough master mix for WELLS_PER_ASPIRATE wells at a time,
        then dispense 4.6 uL into each destination well sequentially.
        Picks up a new tip only when the current tip is exhausted.
        """
        chunk_size = WELLS_PER_ASPIRATE
        for chunk_start in range(0, len(dest_wells), chunk_size):
            chunk = dest_wells[chunk_start : chunk_start + chunk_size]
            aspirate_vol = MASTERMIX_VOL_PER_WELL * len(chunk) + DISPENSE_HEADROOM

            pipette.pick_up_tip()
            pipette.aspirate(aspirate_vol, mastermix_well)
            for well in chunk:
                pipette.dispense(MASTERMIX_VOL_PER_WELL, well)
            # Blow out remaining headroom volume back to reservoir
            pipette.blow_out(mastermix_well)
            pipette.drop_tip()

    # ------------------------------------------------------------------ #
    # Main protocol: fill all three 384-well plates                       #
    # ------------------------------------------------------------------ #
    protocol.comment(
        f"Starting PCR Master Mix distribution: "
        f"{MASTERMIX_VOL_PER_WELL} uL per well x {TOTAL_WELLS_PER_PLATE} wells "
        f"x {NUM_384_PLATES} plates."
    )

    for plate_idx, plate in enumerate(pcr_plates):
        protocol.comment(f"Processing plate {plate_idx + 1} of {NUM_384_PLATES}...")
        all_wells = plate.wells()  # returns all 384 wells in row-major order
        multi_dispense_to_wells(all_wells)

    protocol.comment("Protocol complete. All 384-well PCR plates have been filled.")