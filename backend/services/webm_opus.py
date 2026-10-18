from dataclasses import dataclass

ID_EBML = bytes.fromhex("1A45DFA3")
ID_DOCTYPE = bytes.fromhex("4282")
ID_SEGMENT = bytes.fromhex("18538067")
ID_INFO = bytes.fromhex("1549A966")
ID_TIMESTAMP_SCALE = bytes.fromhex("2AD7B1")
ID_TRACKS = bytes.fromhex("1654AE6B")
ID_TRACK_ENTRY = bytes.fromhex("AE")
ID_TRACK_NUMBER = bytes.fromhex("D7")
ID_TRACK_TYPE = bytes.fromhex("83")
ID_CODEC_ID = bytes.fromhex("86")
ID_CODEC_PRIVATE = bytes.fromhex("63A2")
ID_CLUSTER = bytes.fromhex("1F43B675")
ID_SIMPLE_BLOCK = bytes.fromhex("A3")
ID_BLOCK_GROUP = bytes.fromhex("A0")
ID_BLOCK = bytes.fromhex("A1")

MASTER_IDS = {
    ID_EBML,
    ID_SEGMENT,
    ID_INFO,
    ID_TRACKS,
    ID_TRACK_ENTRY,
    ID_CLUSTER,
    ID_BLOCK_GROUP,
}

# Opus TOC 的 config 对应每帧时长，单位微秒。见 RFC 6716。
_FRAME_US = [
    10_000, 20_000, 40_000, 60_000,
    10_000, 20_000, 40_000, 60_000,
    10_000, 20_000, 40_000, 60_000,
    10_000, 20_000,
    10_000, 20_000,
    2_500, 5_000, 10_000, 20_000,
    2_500, 5_000, 10_000, 20_000,
    2_500, 5_000, 10_000, 20_000,
    2_500, 5_000, 10_000, 20_000,
]


class WebmParseError(Exception):
    pass


class AudioFormatError(Exception):
    pass


@dataclass
class _Element:
    element_id: bytes
    start: int
    end: int


@dataclass
class _Track:
    number: int | None = None
    track_type: int | None = None
    codec_id: str = ""
    codec_private: bytes | None = None


def measure_webm_opus_duration_us(data: bytes) -> int:
    """返回 Opus 音频流的时长，单位微秒。没有音频包时返回 0。

    浏览器生成的 WebM 经常没有 Segment Info Duration。这里不读取该字段，
    而是把 Opus 音轨里每个音频包的时长相加。
    """
    try:
        return _measure(data)
    except WebmParseError as exc:
        raise AudioFormatError("无法解析 WebM") from exc


def _measure(data: bytes) -> int:
    if len(data) < 4 or not data.startswith(ID_EBML):
        raise AudioFormatError("不是 WebM")
    elements = _parse_children(data, 0, len(data))
    doc_type = None
    segment = None
    for element in elements:
        if element.element_id == ID_EBML:
            doc_type = _read_doc_type(data, element)
        elif element.element_id == ID_SEGMENT and segment is None:
            segment = element
    if doc_type != "webm" or segment is None:
        raise AudioFormatError("不是 WebM")
    return _measure_segment(data, segment)


def _measure_segment(data: bytes, segment: _Element) -> int:
    children = _parse_children(data, segment.start, segment.end)
    tracks: list[_Track] = []
    for element in children:
        if element.element_id == ID_INFO:
            _read_timestamp_scale(data, element)
        elif element.element_id == ID_TRACKS:
            tracks.extend(_read_tracks(data, element))
    opus_numbers = _opus_track_numbers(tracks)
    total = 0
    for element in children:
        if element.element_id != ID_CLUSTER:
            continue
        total += _cluster_opus_duration_us(data, element, opus_numbers)
    return total


def _opus_track_numbers(tracks: list[_Track]) -> set[int]:
    numbers: set[int] = set()
    saw_opus_codec = False
    for track in tracks:
        if track.codec_id != "A_OPUS":
            continue
        saw_opus_codec = True
        if track.track_type not in (None, 2) or track.number is None:
            raise AudioFormatError("Opus 音轨不完整")
        private = track.codec_private or b""
        if len(private) < 19 or not private.startswith(b"OpusHead"):
            raise AudioFormatError("缺少 Opus 标识")
        numbers.add(track.number)
    if not saw_opus_codec or not numbers:
        raise AudioFormatError("不是 Opus")
    return numbers


def _read_doc_type(data: bytes, element: _Element) -> str:
    for child in _parse_children(data, element.start, element.end):
        if child.element_id == ID_DOCTYPE:
            return _read_text(data[child.start:child.end])
    raise AudioFormatError("缺少 DocType")


def _read_timestamp_scale(data: bytes, element: _Element) -> int:
    for child in _parse_children(data, element.start, element.end):
        if child.element_id == ID_TIMESTAMP_SCALE:
            scale = _read_uint(data[child.start:child.end])
            if scale <= 0:
                raise AudioFormatError("时间刻度无效")
            return scale
    return 1_000_000


def _read_tracks(data: bytes, element: _Element) -> list[_Track]:
    tracks = []
    for child in _parse_children(data, element.start, element.end):
        if child.element_id != ID_TRACK_ENTRY:
            continue
        track = _Track()
        for field in _parse_children(data, child.start, child.end):
            payload = data[field.start:field.end]
            if field.element_id == ID_TRACK_NUMBER:
                track.number = _read_uint(payload)
            elif field.element_id == ID_TRACK_TYPE:
                track.track_type = _read_uint(payload)
            elif field.element_id == ID_CODEC_ID:
                track.codec_id = _read_text(payload)
            elif field.element_id == ID_CODEC_PRIVATE:
                track.codec_private = payload
        tracks.append(track)
    return tracks


def _cluster_opus_duration_us(
    data: bytes, element: _Element, opus_numbers: set[int]
) -> int:
    total = 0
    for child in _parse_children(data, element.start, element.end):
        if child.element_id == ID_SIMPLE_BLOCK:
            total += _block_opus_duration_us(data[child.start:child.end], opus_numbers)
        elif child.element_id == ID_BLOCK_GROUP:
            for block in _parse_children(data, child.start, child.end):
                if block.element_id == ID_BLOCK:
                    total += _block_opus_duration_us(
                        data[block.start:block.end], opus_numbers
                    )
    return total


def _block_opus_duration_us(payload: bytes, opus_numbers: set[int]) -> int:
    track_number, frames = _split_block(payload)
    if track_number not in opus_numbers:
        return 0
    return sum(_opus_packet_duration_us(frame) for frame in frames)


def _split_block(payload: bytes) -> tuple[int, list[bytes]]:
    track_number, _, position = _read_vint(payload, 0)
    if position + 3 > len(payload):
        raise WebmParseError("音频块过短")
    flags = payload[position + 2]
    frames = _delace(payload[position + 3:], (flags >> 1) & 0x03)
    return track_number, frames


def _delace(data: bytes, lacing: int) -> list[bytes]:
    if lacing == 0:
        if not data:
            raise WebmParseError("音频帧为空")
        return [data]
    if not data:
        raise WebmParseError("缺少分帧信息")
    count = data[0] + 1
    position = 1
    if lacing == 2:
        remaining = len(data) - position
        if remaining <= 0 or remaining % count != 0:
            raise WebmParseError("等长分帧无效")
        size = remaining // count
        return [
            data[position + index * size:position + (index + 1) * size]
            for index in range(count)
        ]
    if lacing == 1:
        sizes = []
        for _ in range(count - 1):
            size = 0
            while True:
                if position >= len(data):
                    raise WebmParseError("Xiph 分帧无效")
                byte = data[position]
                position += 1
                size += byte
                if byte != 255:
                    break
            sizes.append(size)
        frames = []
        for size in sizes:
            frames.append(_take_frame(data, position, size))
            position += size
        frames.append(_take_frame(data, position, len(data) - position))
        return frames
    if lacing == 3:
        if count == 1:
            return [_take_frame(data, position, len(data) - position)]
        first_size, _, position = _read_vint(data, position)
        sizes = [first_size]
        for _ in range(count - 2):
            difference, position = _read_signed_vint(data, position)
            sizes.append(sizes[-1] + difference)
        frames = []
        for size in sizes:
            frames.append(_take_frame(data, position, size))
            position += size
        frames.append(_take_frame(data, position, len(data) - position))
        return frames
    raise WebmParseError("未知的分帧方式")


def _take_frame(data: bytes, position: int, size: int) -> bytes:
    if size <= 0 or position < 0 or position + size > len(data):
        raise WebmParseError("音频帧长度无效")
    return data[position:position + size]


def _opus_packet_duration_us(packet: bytes) -> int:
    if not packet:
        raise WebmParseError("Opus 包为空")
    toc = packet[0]
    config = toc >> 3
    if config > 31:
        raise WebmParseError("Opus TOC 无效")
    frame_us = _FRAME_US[config]
    code = toc & 0x03
    if code == 0:
        frames = 1
    elif code != 3:
        frames = 2
    else:
        if len(packet) < 2:
            raise WebmParseError("Opus 帧数缺失")
        frames = packet[1] & 0x3F
    if frames < 1 or frames > 48:
        raise WebmParseError("Opus 帧数无效")
    total = frames * frame_us
    if total <= 0 or total > 120_000:
        raise WebmParseError("Opus 包时长无效")
    return total


def _parse_children(data: bytes, start: int, end: int) -> list[_Element]:
    elements = []
    position = start
    while position < end:
        if end - position < 2:
            break
        element_id, position = _read_element_id(data, position)
        size, unknown, position = _read_data_size(data, position)
        if unknown:
            if element_id not in MASTER_IDS:
                raise WebmParseError("未知元素长度无效")
            payload_end = end
        else:
            payload_end = position + size
            if payload_end > end:
                raise WebmParseError("元素超出父节点")
        elements.append(_Element(element_id, position, payload_end))
        position = payload_end
        if len(elements) > 200_000:
            raise WebmParseError("元素过多")
    return elements


def _read_element_id(data: bytes, position: int) -> tuple[bytes, int]:
    length = _vint_length(data, position)
    end = position + length
    return data[position:end], end


def _read_data_size(data: bytes, position: int) -> tuple[int, bool, int]:
    value, all_ones, end = _read_vint(data, position)
    return value, all_ones, end


def _read_vint(data: bytes, position: int) -> tuple[int, bool, int]:
    length = _vint_length(data, position)
    end = position + length
    raw = int.from_bytes(data[position:end], "big")
    width = 7 * length
    value = raw & ((1 << width) - 1)
    return value, value == (1 << width) - 1, end


def _read_signed_vint(data: bytes, position: int) -> tuple[int, int]:
    length = _vint_length(data, position)
    value, _, end = _read_vint(data, position)
    bias = (1 << (7 * length - 1)) - 1
    return value - bias, end


def _vint_length(data: bytes, position: int) -> int:
    if position >= len(data):
        raise WebmParseError("数据截断")
    first = data[position]
    mask = 0x80
    length = 1
    while length <= 8 and not (first & mask):
        mask >>= 1
        length += 1
    if length > 8 or position + length > len(data):
        raise WebmParseError("变长整数无效")
    return length


def _read_uint(payload: bytes) -> int:
    if not payload:
        raise WebmParseError("整数为空")
    return int.from_bytes(payload, "big")


def _read_text(payload: bytes) -> str:
    try:
        return payload.split(b"\x00", 1)[0].decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise AudioFormatError("文本无效") from exc
