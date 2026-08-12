import unittest
from unittest.mock import AsyncMock, Mock, patch

from StellariaPact.share import BusinessRuleError, UnitOfWork


class _DatabaseHandler:
    def __init__(self, session):
        self.session = session

    def get_session(self):
        return self.session


class UnitOfWorkLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_business_rule_error_rolls_back_at_debug_level(self) -> None:
        session = Mock()
        session.rollback = AsyncMock()
        session.close = AsyncMock()
        error = BusinessRuleError("预期的业务拒绝")

        with patch("StellariaPact.share.UnitOfWork.logger") as logger:
            with self.assertRaises(BusinessRuleError):
                async with UnitOfWork(_DatabaseHandler(session)):
                    raise error

        session.rollback.assert_awaited_once()
        session.close.assert_awaited_once()
        logger.debug.assert_called_once_with(
            "UnitOfWork 检测到异常，正在回滚事务: %s: %s",
            "BusinessRuleError",
            error,
        )
        logger.warning.assert_not_called()

    async def test_unexpected_error_rolls_back_at_warning_level(self) -> None:
        session = Mock()
        session.rollback = AsyncMock()
        session.close = AsyncMock()
        error = RuntimeError("非预期错误")

        with patch("StellariaPact.share.UnitOfWork.logger") as logger:
            with self.assertRaises(RuntimeError):
                async with UnitOfWork(_DatabaseHandler(session)):
                    raise error

        session.rollback.assert_awaited_once()
        session.close.assert_awaited_once()
        logger.warning.assert_called_once_with(
            "UnitOfWork 检测到异常，正在回滚事务: %s: %s",
            "RuntimeError",
            error,
        )
        logger.debug.assert_not_called()

    def test_business_rule_error_remains_a_permission_error(self) -> None:
        self.assertIsInstance(BusinessRuleError("业务拒绝"), PermissionError)


if __name__ == "__main__":
    unittest.main()
