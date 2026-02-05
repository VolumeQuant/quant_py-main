"""
에러 핸들링 모듈 - Skip & Log 패턴

Features:
- 구조화된 로깅 (파일 + 콘솔)
- 실패 종목 추적
- 재시도 메커니즘
- 에러 카테고리 분류
"""

import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Set, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
import json
import traceback


class ErrorCategory(Enum):
    """에러 유형 분류"""
    NETWORK = "network"           # 네트워크/연결 오류
    API_RATE_LIMIT = "rate_limit" # API 호출 제한
    DATA_NOT_FOUND = "not_found"  # 데이터 없음
    PARSE_ERROR = "parse"         # 파싱 실패
    VALIDATION = "validation"     # 데이터 검증 실패
    TIMEOUT = "timeout"           # 타임아웃
    AUTH = "auth"                 # 인증 오류
    UNKNOWN = "unknown"           # 기타


@dataclass
class ErrorRecord:
    """개별 에러 기록"""
    ticker: str
    category: ErrorCategory
    message: str
    timestamp: datetime
    exception_type: Optional[str] = None
    exception_msg: Optional[str] = None
    retry_count: int = 0

    def to_dict(self) -> Dict:
        return {
            'ticker': self.ticker,
            'category': self.category.value,
            'message': self.message,
            'timestamp': self.timestamp.isoformat(),
            'exception_type': self.exception_type,
            'exception_msg': self.exception_msg,
            'retry_count': self.retry_count,
        }


class ErrorTracker:
    """
    중앙 에러 추적 시스템 - Skip & Log 패턴

    사용법:
        tracker = ErrorTracker(log_dir=Path("logs"))

        try:
            data = fetch_data(ticker)
        except Exception as e:
            tracker.log_error(ticker, ErrorCategory.NETWORK, "데이터 수집 실패", e)
            continue  # Skip & Log

        # 마지막에 요약
        print(tracker.get_summary())
        tracker.save_error_log()
    """

    def __init__(self, log_dir: Path = None, name: str = "quant"):
        self.log_dir = log_dir or Path("logs")
        self.log_dir.mkdir(exist_ok=True)
        self.name = name

        self.errors: List[ErrorRecord] = []
        self.failed_tickers: Set[str] = set()
        self.warnings: List[Dict] = []
        self.retry_counts: Dict[str, int] = {}

        self._setup_logging()

    def _setup_logging(self) -> None:
        """파일 및 콘솔 로깅 설정"""
        self.logger = logging.getLogger(self.name)
        self.logger.setLevel(logging.DEBUG)

        # 기존 핸들러 제거 (중복 방지)
        self.logger.handlers = []

        # 파일 핸들러 (상세 로그)
        log_file = self.log_dir / f"{self.name}_{datetime.now().strftime('%Y%m%d')}.log"
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_format)
        self.logger.addHandler(file_handler)

        # 콘솔 핸들러 (WARNING 이상만)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)
        console_format = logging.Formatter('%(levelname)s: %(message)s')
        console_handler.setFormatter(console_format)
        self.logger.addHandler(console_handler)

    def log_error(
        self,
        ticker: str,
        category: ErrorCategory,
        message: str,
        exception: Optional[Exception] = None,
    ) -> None:
        """
        에러 기록 및 실패 종목 추적

        Args:
            ticker: 종목 코드
            category: 에러 유형
            message: 설명 메시지
            exception: 원본 예외 (선택)
        """
        record = ErrorRecord(
            ticker=ticker,
            category=category,
            message=message,
            timestamp=datetime.now(),
            exception_type=type(exception).__name__ if exception else None,
            exception_msg=str(exception) if exception else None,
            retry_count=self.retry_counts.get(ticker, 0),
        )

        self.errors.append(record)
        self.failed_tickers.add(ticker)

        # 로그 기록
        log_msg = f"[{ticker}] {category.value}: {message}"
        if exception:
            log_msg += f" | {type(exception).__name__}: {exception}"

        self.logger.error(log_msg)

    def log_warning(self, ticker: str, message: str) -> None:
        """
        경고 기록 (복구 가능한 문제)

        Args:
            ticker: 종목 코드
            message: 경고 메시지
        """
        self.warnings.append({
            'ticker': ticker,
            'message': message,
            'timestamp': datetime.now().isoformat(),
        })
        self.logger.warning(f"[{ticker}] {message}")

    def log_info(self, message: str) -> None:
        """정보성 메시지 기록"""
        self.logger.info(message)

    def log_debug(self, message: str) -> None:
        """디버그 메시지 기록"""
        self.logger.debug(message)

    def get_failed_tickers(self) -> List[str]:
        """실패한 종목 목록 반환"""
        return list(self.failed_tickers)

    def get_retry_candidates(self, max_retries: int = 3) -> List[str]:
        """
        재시도 가능한 종목 반환

        Args:
            max_retries: 최대 재시도 횟수

        Returns:
            재시도 대상 종목 목록
        """
        candidates = []
        for ticker in self.failed_tickers:
            if self.retry_counts.get(ticker, 0) < max_retries:
                candidates.append(ticker)
        return candidates

    def mark_retry(self, ticker: str) -> int:
        """
        재시도 횟수 증가

        Returns:
            현재 재시도 횟수
        """
        self.retry_counts[ticker] = self.retry_counts.get(ticker, 0) + 1
        return self.retry_counts[ticker]

    def mark_success(self, ticker: str) -> None:
        """성공 시 실패 목록에서 제거"""
        self.failed_tickers.discard(ticker)

    def save_error_log(self, path: Optional[Path] = None) -> Path:
        """
        상세 에러 로그를 JSON으로 저장

        Returns:
            저장된 파일 경로
        """
        if path is None:
            path = self.log_dir / f"error_detail_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        output = {
            'generated_at': datetime.now().isoformat(),
            'summary': self.get_summary(),
            'errors': [e.to_dict() for e in self.errors],
            'warnings': self.warnings,
            'failed_tickers': list(self.failed_tickers),
        }

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        self.logger.info(f"에러 로그 저장: {path}")
        return path

    def get_summary(self) -> Dict:
        """
        에러 요약 통계

        Returns:
            Dict:
            - total_errors: 총 에러 수
            - by_category: 카테고리별 에러 수
            - failed_ticker_count: 실패 종목 수
            - warning_count: 경고 수
            - retry_pending: 재시도 대기 종목 수
        """
        by_category = {}
        for error in self.errors:
            cat = error.category.value
            by_category[cat] = by_category.get(cat, 0) + 1

        return {
            'total_errors': len(self.errors),
            'by_category': by_category,
            'failed_ticker_count': len(self.failed_tickers),
            'warning_count': len(self.warnings),
            'retry_pending': len(self.get_retry_candidates()),
        }

    def print_summary(self) -> None:
        """요약 출력"""
        summary = self.get_summary()
        print(f"\n[에러 요약]")
        print(f"  총 에러: {summary['total_errors']}건")
        print(f"  실패 종목: {summary['failed_ticker_count']}개")
        print(f"  경고: {summary['warning_count']}건")

        if summary['by_category']:
            print(f"  카테고리별:")
            for cat, count in summary['by_category'].items():
                print(f"    - {cat}: {count}건")

    def reset(self) -> None:
        """에러 기록 초기화"""
        self.errors = []
        self.failed_tickers = set()
        self.warnings = []
        self.retry_counts = {}


def with_error_handling(
    error_tracker: ErrorTracker,
    category: ErrorCategory = ErrorCategory.UNKNOWN,
    default_return: Any = None,
):
    """
    에러 처리 데코레이터 - Skip & Log 패턴

    사용법:
        tracker = ErrorTracker()

        @with_error_handling(tracker, ErrorCategory.NETWORK)
        def fetch_data(ticker):
            ...

    Args:
        error_tracker: ErrorTracker 인스턴스
        category: 기본 에러 카테고리
        default_return: 에러 시 반환값
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # ticker 파라미터 찾기
            ticker = kwargs.get('ticker') or (args[0] if args else 'unknown')

            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_tracker.log_error(
                    ticker=str(ticker),
                    category=category,
                    message=f"{func.__name__} 실행 실패",
                    exception=e,
                )
                return default_return

        return wrapper
    return decorator


def with_error_handling_async(
    error_tracker: ErrorTracker,
    category: ErrorCategory = ErrorCategory.UNKNOWN,
    default_return: Any = None,
):
    """
    비동기 함수용 에러 처리 데코레이터

    사용법:
        tracker = ErrorTracker()

        @with_error_handling_async(tracker, ErrorCategory.API_RATE_LIMIT)
        async def fetch_data_async(ticker):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            ticker = kwargs.get('ticker') or (args[0] if args else 'unknown')

            try:
                return await func(*args, **kwargs)
            except Exception as e:
                error_tracker.log_error(
                    ticker=str(ticker),
                    category=category,
                    message=f"{func.__name__} 실행 실패",
                    exception=e,
                )
                return default_return

        return wrapper
    return decorator


# 편의 함수
def categorize_exception(e: Exception) -> ErrorCategory:
    """
    예외 타입에 따른 카테고리 자동 분류

    Args:
        e: 예외 객체

    Returns:
        적절한 ErrorCategory
    """
    error_name = type(e).__name__.lower()
    error_msg = str(e).lower()

    if 'timeout' in error_name or 'timeout' in error_msg:
        return ErrorCategory.TIMEOUT
    elif 'connection' in error_name or 'network' in error_msg:
        return ErrorCategory.NETWORK
    elif 'rate' in error_msg or 'limit' in error_msg or '429' in error_msg:
        return ErrorCategory.API_RATE_LIMIT
    elif 'notfound' in error_name or '404' in error_msg or 'not found' in error_msg:
        return ErrorCategory.DATA_NOT_FOUND
    elif 'parse' in error_name or 'json' in error_name or 'decode' in error_msg:
        return ErrorCategory.PARSE_ERROR
    elif 'auth' in error_name or 'unauthorized' in error_msg or '401' in error_msg:
        return ErrorCategory.AUTH
    elif 'valid' in error_name or 'valid' in error_msg:
        return ErrorCategory.VALIDATION
    else:
        return ErrorCategory.UNKNOWN


if __name__ == '__main__':
    # 테스트
    tracker = ErrorTracker(log_dir=Path("logs"), name="test")

    # 에러 기록 테스트
    tracker.log_error("005930", ErrorCategory.NETWORK, "연결 실패", Exception("Connection refused"))
    tracker.log_error("000660", ErrorCategory.DATA_NOT_FOUND, "데이터 없음")
    tracker.log_warning("035720", "데이터 불완전")

    # 요약 출력
    tracker.print_summary()

    # 로그 저장
    log_path = tracker.save_error_log()
    print(f"\n로그 저장 완료: {log_path}")
