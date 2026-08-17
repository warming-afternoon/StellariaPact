import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from StellariaPact.cogs.Intake.services.IntakeDraftService import IntakeDraftService
from StellariaPact.cogs.Intake.services.IntakeReviewService import IntakeReviewService
from StellariaPact.cogs.ThreadManage.Cog import ThreadManageCog
from StellariaPact.cogs.ThreadManage.dto.UpdateProposalContentDto import (
    UpdateProposalContentDto,
)
from StellariaPact.share import BusinessRuleError, StringUtils

FORBIDDEN_CHARACTERS = ("\\", "/", ":", "*", "?", '"', "<", ">", "|")
ERROR_MESSAGE = '提案标题不能包含以下半角符号：\\ / : * ? " < > |'


class ProposalTitleValidatorTests(unittest.TestCase):
    def test_each_forbidden_character_is_rejected_at_every_position(self) -> None:
        title_templates = ("{}提案", "社区{}提案", "社区提案{}")

        for character in FORBIDDEN_CHARACTERS:
            for title_template in title_templates:
                with self.subTest(character=character, title_template=title_template):
                    with self.assertRaises(BusinessRuleError) as error:
                        StringUtils.validate_proposal_title(
                            title_template.format(character)
                        )

                    self.assertEqual(str(error.exception), ERROR_MESSAGE)

    def test_multiple_forbidden_characters_return_stable_error(self) -> None:
        with self.assertRaises(BusinessRuleError) as error:
            StringUtils.validate_proposal_title('社区/治理:提案?"')

        self.assertEqual(str(error.exception), ERROR_MESSAGE)

    def test_valid_titles_are_accepted(self) -> None:
        valid_titles = (
            "关于社区徽章的提案",
            "Proposal 2026",
            "提案，第１版。",
            "全角＼／：＊？“”＜＞｜可用",
        )

        for title in valid_titles:
            with self.subTest(title=title):
                StringUtils.validate_proposal_title(title)


class ProposalTitleEntryPointTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _intake_submission(title: str) -> SimpleNamespace:
        return SimpleNamespace(
            author_id=1,
            guild_id=2,
            title=title,
            reason="reason",
            motion="motion",
            implementation="implementation",
            executor="executor",
        )

    async def test_new_intake_rejects_invalid_title_before_database_access(self) -> None:
        service = IntakeDraftService(SimpleNamespace(db_handler=Mock()))

        with patch(
            "StellariaPact.cogs.Intake.services.IntakeDraftService.UnitOfWork"
        ) as unit_of_work:
            with self.assertRaises(BusinessRuleError):
                await service.process_submit_intake(
                    self._intake_submission("新/提案"), Mock()
                )

        unit_of_work.assert_not_called()

    async def test_intake_edit_rejects_invalid_title_before_database_access(self) -> None:
        service = IntakeReviewService(SimpleNamespace(db_handler=Mock()), Mock())

        with patch(
            "StellariaPact.cogs.Intake.services.IntakeReviewService.UnitOfWork"
        ) as unit_of_work:
            with self.assertRaises(BusinessRuleError):
                await service.edit_intake(
                    1, self._intake_submission("修改|提案")
                )

        unit_of_work.assert_not_called()

    async def test_established_proposal_edit_rejects_before_database_access(self) -> None:
        cog = ThreadManageCog(SimpleNamespace(db_handler=Mock()))
        dto = UpdateProposalContentDto(
            proposal_id=1,
            proposer_id=2,
            title="修改?提案",
            reason="reason",
            motion="motion",
            implementation="implementation",
            executor="executor",
            thread_id=3,
        )

        with patch(
            "StellariaPact.cogs.ThreadManage.Cog.UnitOfWork"
        ) as unit_of_work:
            with self.assertRaises(BusinessRuleError):
                await cog._handle_update_within_uow(dto)

        unit_of_work.assert_not_called()


if __name__ == "__main__":
    unittest.main()
