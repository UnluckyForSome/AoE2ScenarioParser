from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import BinaryIO, List, Optional

from ._io import BinaryReader, BinaryWriter
from ._support.strings import (
    read_u32_length_prefixed_str,
    write_i32_str,
)


class AIErrorCode(IntEnum):
    ConstantAlreadyDefined = 0
    FileOpenFailed = 1
    FileReadFailed = 2
    InvalidIdentifier = 3
    InvalidKeyword = 4
    InvalidPreprocessorDirective = 5
    ListFull = 6
    MissingArrow = 7
    MissingClosingParenthesis = 8
    MissingClosingQuote = 9
    MissingEndIf = 10
    MissingFileName = 11
    MissingIdentifier = 12
    MissingKeyword = 13
    MissingLHS = 14
    MissingOpeningParenthesis = 15
    MissingPreprocessorSymbol = 16
    MissingRHS = 17
    NoRules = 18
    PreprocessorNestingTooDeep = 19
    RuleTooLong = 20
    StringTableFull = 21
    UndocumentedError = 22
    UnexpectedElse = 23
    UnexpectedEndIf = 24
    UnexpectedError = 25
    UnexpectedEOF = 26


@dataclass(slots=True)
class AIErrorInfo:
    filename: str
    line_number: int
    description: str
    error_code: AIErrorCode

    @staticmethod
    def _parse_bytes(raw: bytes) -> str:
        b = bytearray(raw)
        try:
            end = b.index(0)
            b = b[:end]
        except ValueError:
            pass
        if not b:
            return "<empty>"
        # Rust fix: String::from_utf8_lossy
        return bytes(b).decode("utf-8", errors="replace")

    @staticmethod
    def read_from(reader: BinaryIO) -> "AIErrorInfo":
        r = BinaryReader(reader)
        filename_bytes = r.read_bytes(257)
        line_number = r.read_i32()
        description_bytes = r.read_bytes(128)
        raw_code = r.read_u32()
        try:
            code = AIErrorCode(raw_code)
        except Exception:
            code = AIErrorCode.UndocumentedError
        return AIErrorInfo(
            filename=AIErrorInfo._parse_bytes(filename_bytes),
            line_number=line_number,
            description=AIErrorInfo._parse_bytes(description_bytes),
            error_code=code,
        )

    def write_to(self, writer: BinaryIO) -> None:
        w = BinaryWriter(writer)
        filename_bytes = bytearray(257)
        fb = self.filename.encode("utf-8", errors="replace")
        filename_bytes[: len(fb)] = fb
        w.write_bytes(bytes(filename_bytes))
        w.write_i32(self.line_number)
        desc_bytes = bytearray(128)
        db = self.description.encode("utf-8", errors="replace")
        desc_bytes[: len(db)] = db
        w.write_bytes(bytes(desc_bytes))
        w.write_u32(int(self.error_code))


@dataclass(slots=True)
class AIFile:
    filename: str
    content: str

    @staticmethod
    def read_from(reader: BinaryIO) -> "AIFile":
        # Rust expects Some(...) here, panics otherwise.
        filename = read_u32_length_prefixed_str(reader)
        if filename is None:
            raise ValueError("missing ai file name")
        content = read_u32_length_prefixed_str(reader)
        if content is None:
            raise ValueError("empty ai file?")
        return AIFile(filename=filename, content=content)

    def write_to(self, writer: BinaryIO) -> None:
        write_i32_str(writer, self.filename)
        write_i32_str(writer, self.content)


@dataclass(slots=True)
class AIInfo:
    error: Optional[AIErrorInfo] = None
    files: List[AIFile] = field(default_factory=list)

    @staticmethod
    def read_from(reader: BinaryIO) -> Optional["AIInfo"]:
        # Some legacy scenarios appear to have malformed/absent AIInfo blocks (Joan 6) despite being in a version
        # range where the block is typically present. The Rust implementation will error in that case.
        #
        # For our bridge pipeline, AI blobs are not semantically important (and are diff-ignored), so we
        # best-effort parse and, if the block is clearly malformed, rewind (when possible) and treat it
        # as absent to keep overall scenario parsing aligned.
        start_pos: int | None = None
        if hasattr(reader, "tell") and hasattr(reader, "seek"):
            try:
                start_pos = int(reader.tell())
            except Exception:
                start_pos = None

        r = BinaryReader(reader)
        try:
            has_ai_files = r.read_u32() != 0
            has_error = r.read_u32() != 0
            if not has_error and not has_ai_files:
                return None

            error = AIErrorInfo.read_from(reader) if has_error else None
            num_ai_files = r.read_u32()

            # Guard against obvious misalignment (e.g. interpreting some later block as an AI file count).
            if num_ai_files > 10_000:
                raise ValueError(f"implausible ai file count: {num_ai_files}")

            files: List[AIFile] = []
            for _ in range(num_ai_files):
                files.append(AIFile.read_from(reader))
            return AIInfo(error=error, files=files)
        except Exception:
            if start_pos is not None:
                try:
                    reader.seek(start_pos)
                    return None
                except Exception:
                    pass
            raise

    def write_to(self, writer: BinaryIO) -> None:
        w = BinaryWriter(writer)
        w.write_u32(1 if self.files else 0)
        if self.error is not None:
            w.write_u32(1)
            self.error.write_to(writer)
        else:
            w.write_u32(0)
        if self.files:
            w.write_u32(len(self.files))
            for f in self.files:
                f.write_to(writer)

