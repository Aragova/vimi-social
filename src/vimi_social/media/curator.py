from vimi_social.domain.media import (
    CuratorAssessment,
    CuratorDecision,
    RightsBasis,
)
from vimi_social.domain.source import CandidateContent

_ALLOWED_RIGHTS = {
    RightsBasis.USER_CONFIRMED,
    RightsBasis.CONNECTOR_AUTHORIZED,
    RightsBasis.OWNED_SOURCE,
    RightsBasis.LICENSED_SOURCE,
}


class CandidateCurator:
    """Deterministic eligibility boundary before remote media acquisition."""

    def assess(
        self,
        candidate: CandidateContent,
        rights_basis: RightsBasis,
    ) -> CuratorAssessment:
        if candidate.media_type != "video":
            return CuratorAssessment(
                decision=CuratorDecision.BLOCKED,
                acquisition_url=None,
                reasons=("candidate_is_not_video",),
            )
        if rights_basis not in _ALLOWED_RIGHTS:
            return CuratorAssessment(
                decision=CuratorDecision.RIGHTS_REVIEW_REQUIRED,
                acquisition_url=None,
                reasons=(candidate.provenance_hint, "reuse_rights_not_confirmed"),
            )

        acquisition_url = candidate.connector_metadata.get("acquisition_url")
        if not isinstance(acquisition_url, str) or not acquisition_url:
            return CuratorAssessment(
                decision=CuratorDecision.BLOCKED,
                acquisition_url=None,
                reasons=("connector_has_no_permitted_media_reference",),
            )
        return CuratorAssessment(
            decision=CuratorDecision.ACQUISITION_ALLOWED,
            acquisition_url=acquisition_url,
            reasons=("rights_basis_present", "connector_media_reference_present"),
        )
