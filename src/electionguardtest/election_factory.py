from datetime import datetime
import os
import uuid
from dataclasses import dataclass
from typing import TypeVar, Callable, Optional, Tuple, List

from hypothesis.strategies import (
    composite,
    emails,
    integers,
    text,
    SearchStrategy,
)

from electionguard.ballot import PlaintextBallot
from electionguard.election import CiphertextElectionContext, ElectionConstants
from electionguard.election_builder import ElectionBuilder
from electionguard.encrypt import EncryptionDevice, contest_from, generate_device_uuid
from electionguard.group import ElementModP, TWO_MOD_Q
from electionguard.guardian import Guardian, GuardianRecord
from electionguard.key_ceremony import CeremonyDetails
from electionguard.key_ceremony_mediator import KeyCeremonyMediator
from electionguard.manifest import (
    BallotStyle,
    Manifest,
    ElectionType,
    InternalManifest,
    generate_placeholder_selections_from,
    GeopoliticalUnit,
    Candidate,
    Party,
    ContestDescription,
    SelectionDescription,
    ReportingUnitType,
    VoteVariationType,
    contest_description_with_placeholders_from,
    CandidateContestDescription,
    ReferendumContestDescription,
)
from electionguard.utils import get_optional

from electionguardtest.key_ceremony_helper import KeyCeremonyHelper

_T = TypeVar("_T")
_DrawType = Callable[[SearchStrategy[_T]], _T]

data = os.path.realpath(os.path.join(__file__, "../../../data"))

NUMBER_OF_GUARDIANS = 5
QUORUM = 3


@dataclass
class AllPublicElectionData:
    """All public data for election"""

    manifest: Manifest
    internal_manifest: InternalManifest
    context: CiphertextElectionContext
    constants: ElectionConstants
    guardians: List[GuardianRecord]


@dataclass
class AllPrivateElectionData:
    """All private data for election"""

    guardians: List[Guardian]


class ElectionFactory:
    """Factory to create elections"""

    simple_election_manifest_file_name = "election_manifest_simple.json"

    def get_simple_manifest_from_file(self) -> Manifest:
        return self._get_manifest_from_file(self.simple_election_manifest_file_name)

    @staticmethod
    def get_hamilton_manifest_from_file() -> Manifest:
        with open(
            os.path.join(data, "hamilton-county", "election_manifest.json"), "r"
        ) as subject:
            result = subject.read()
            target = Manifest.from_json(result)

        return target

    def get_hamilton_manifest_with_encryption_context(
        self,
    ) -> Tuple[AllPublicElectionData, AllPrivateElectionData]:
        guardians: List[Guardian] = []
        guardian_records: List[GuardianRecord] = []

        # Configure the election builder
        manifest = self.get_hamilton_manifest_from_file()
        builder = ElectionBuilder(NUMBER_OF_GUARDIANS, QUORUM, manifest)

        # Run the Key Ceremony
        ceremony_details = CeremonyDetails(NUMBER_OF_GUARDIANS, QUORUM)
        guardians = KeyCeremonyHelper.create_guardians(ceremony_details)
        mediator = KeyCeremonyMediator("key-ceremony-mediator", ceremony_details)
        KeyCeremonyHelper.perform_full_ceremony(guardians, mediator)

        # Final: Joint Key
        joint_key = mediator.publish_joint_key()

        # Publish Guardian Records
        guardian_records = [guardian.publish() for guardian in guardians]

        builder.set_public_key(get_optional(joint_key).joint_public_key)
        builder.set_commitment_hash(get_optional(joint_key).commitment_hash)
        internal_manifest, context = get_optional(builder.build())
        constants = ElectionConstants()

        return (
            AllPublicElectionData(
                manifest,
                internal_manifest,
                context,
                constants,
                guardian_records,
            ),
            AllPrivateElectionData(guardians),
        )

    @staticmethod
    def get_fake_manifest() -> Manifest:
        """
        Get a single fake manifest object that is manually constructed with default values
        """

        fake_ballot_style = BallotStyle("some-ballot-style-id")
        fake_ballot_style.geopolitical_unit_ids = ["some-geopoltical-unit-id"]

        fake_referendum_ballot_selections = [
            # Referendum selections are simply a special case of `candidate` in the object model
            SelectionDescription(
                "some-object-id-affirmative", "some-candidate-id-1", 0
            ),
            SelectionDescription("some-object-id-negative", "some-candidate-id-2", 1),
        ]

        sequence_order = 0
        number_elected = 1
        votes_allowed = 1
        fake_referendum_contest = ReferendumContestDescription(
            "some-referendum-contest-object-id",
            "some-geopoltical-unit-id",
            sequence_order,
            VoteVariationType.one_of_m,
            number_elected,
            votes_allowed,
            "some-referendum-contest-name",
            fake_referendum_ballot_selections,
        )

        fake_candidate_ballot_selections = [
            SelectionDescription(
                "some-object-id-candidate-1", "some-candidate-id-1", 0
            ),
            SelectionDescription(
                "some-object-id-candidate-2", "some-candidate-id-2", 1
            ),
            SelectionDescription(
                "some-object-id-candidate-3", "some-candidate-id-3", 2
            ),
        ]

        sequence_order_2 = 1
        number_elected_2 = 2
        votes_allowed_2 = 2
        fake_candidate_contest = CandidateContestDescription(
            "some-candidate-contest-object-id",
            "some-geopoltical-unit-id",
            sequence_order_2,
            VoteVariationType.one_of_m,
            number_elected_2,
            votes_allowed_2,
            "some-candidate-contest-name",
            fake_candidate_ballot_selections,
        )

        fake_manifest = Manifest(
            spec_version="v0.95",
            election_scope_id="some-scope-id",
            type=ElectionType.unknown,
            start_date=datetime.now(),
            end_date=datetime.now(),
            geopolitical_units=[
                GeopoliticalUnit(
                    "some-geopoltical-unit-id",
                    "some-gp-unit-name",
                    ReportingUnitType.unknown,
                )
            ],
            parties=[Party("some-party-id-1"), Party("some-party-id-2")],
            candidates=[
                Candidate("some-candidate-id-1"),
                Candidate("some-candidate-id-2"),
                Candidate("some-candidate-id-3"),
            ],
            contests=[fake_referendum_contest, fake_candidate_contest],
            ballot_styles=[fake_ballot_style],
        )

        return fake_manifest

    @staticmethod
    def get_fake_ciphertext_election(
        manifest: Manifest, elgamal_public_key: ElementModP
    ) -> Tuple[InternalManifest, CiphertextElectionContext]:
        builder = ElectionBuilder(number_of_guardians=1, quorum=1, manifest=manifest)
        builder.set_public_key(elgamal_public_key)
        builder.set_commitment_hash(TWO_MOD_Q)
        internal_manifest, context = get_optional(builder.build())
        return internal_manifest, context

    # TODO: Move to ballot Factory?
    def get_fake_ballot(
        self, manifest: Manifest = None, ballot_id: str = None
    ) -> PlaintextBallot:
        """
        Get a single Fake Ballot object that is manually constructed with default vaules
        """
        if manifest is None:
            manifest = self.get_fake_manifest()

        if ballot_id is None:
            ballot_id = "some-unique-ballot-id-123"

        fake_ballot = PlaintextBallot(
            ballot_id,
            manifest.ballot_styles[0].object_id,
            [contest_from(manifest.contests[0]), contest_from(manifest.contests[1])],
        )

        return fake_ballot

    @staticmethod
    def _get_manifest_from_file(filename: str) -> Manifest:
        with open(os.path.join(data, filename), "r") as subject:
            result = subject.read()
            manifest = Manifest.from_json(result)

        return manifest

    @staticmethod
    def get_encryption_device() -> EncryptionDevice:
        return EncryptionDevice(
            generate_device_uuid(),
            12345,
            45678,
            f"polling-place-{str(uuid.uuid1())}",
        )


@composite
def get_selection_description_well_formed(
    draw: _DrawType,
    ints=integers(1, 20),
    email_addresses=emails(),
    candidate_id: Optional[str] = None,
    sequence_order: Optional[int] = None,
) -> Tuple[str, SelectionDescription]:
    if candidate_id is None:
        candidate_id = draw(email_addresses)

    object_id = f"{candidate_id}-selection"

    if sequence_order is None:
        sequence_order = draw(ints)

    return (object_id, SelectionDescription(object_id, candidate_id, sequence_order))


@composite
def get_contest_description_well_formed(
    draw: _DrawType,
    ints=integers(1, 20),
    txt=text(),
    email_addresses=emails(),
    selections=get_selection_description_well_formed(),
    sequence_order: Optional[int] = None,
    electoral_district_id: Optional[str] = None,
) -> Tuple[str, ContestDescription]:
    object_id = f"{draw(email_addresses)}-contest"

    if sequence_order is None:
        sequence_order = draw(ints)

    if electoral_district_id is None:
        electoral_district_id = f"{draw(email_addresses)}-gp-unit"

    first_int = draw(ints)
    second_int = draw(ints)

    # TODO ISSUE #33: support more votes than seats for other VoteVariationType options
    number_elected = min(first_int, second_int)
    votes_allowed = number_elected

    selection_descriptions: List[SelectionDescription] = list()
    for i in range(max(first_int, second_int)):
        selection: Tuple[str, SelectionDescription] = draw(selections)
        _, selection_description = selection
        selection_description.sequence_order = i
        selection_descriptions.append(selection_description)

    contest_description = ContestDescription(
        object_id,
        electoral_district_id,
        sequence_order,
        VoteVariationType.n_of_m,
        number_elected,
        votes_allowed,
        draw(txt),
        selection_descriptions,
    )

    placeholder_selections = generate_placeholder_selections_from(
        contest_description, number_elected
    )

    return (
        object_id,
        contest_description_with_placeholders_from(
            contest_description, placeholder_selections
        ),
    )
