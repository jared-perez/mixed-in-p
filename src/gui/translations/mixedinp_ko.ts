<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="ko_KR">
<context>
    <name>AboutDialog</name>
    <message>
        <location filename="../widgets/dialogs/about_dialog.py" line="82"/>
        <location filename="../widgets/dialogs/about_dialog.py" line="121"/>
        <source>Mixed in P</source>
        <translation>Mixed in P</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/about_dialog.py" line="91"/>
        <source>docs</source>
        <translatorcomment>Native script for a non-Latin UI (cf. sample/slicer rule).</translatorcomment>
        <translation>문서</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/about_dialog.py" line="116"/>
        <source>Jared P presents</source>
        <translatorcomment>Left in English as a proper-name credit line (creator name). Could be rendered &quot;Jared P 제공&quot; if a localized credit is preferred. Flag for native review.</translatorcomment>
        <translation>Jared P presents</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/about_dialog.py" line="131"/>
        <source>DJ Audio Analysis Toolkit</source>
        <translatorcomment>&quot;toolkit&quot; → 툴킷 (standard loanword). Noun-phrase tagline.</translatorcomment>
        <translation>DJ 오디오 분석 툴킷</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/about_dialog.py" line="139"/>
        <source>Version {0}</source>
        <translation>버전 {0}</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/about_dialog.py" line="148"/>
        <source>Check for updates</source>
        <translation>업데이트 확인</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/about_dialog.py" line="187"/>
        <source>Analyze audio files to detect BPM and musical key.
Results displayed as harmonic key codes for easy harmonic mixing.

Features:
  - Batch file renaming with Undo
  - Metadata editing
  - Player with built-in slicer for sample lifting
  - Harmonic keyboard
  - BPM detection using beat tracking
  - Key detection using Chroma analysis
  - Spectrum analyzer</source>
        <translatorcomment>조성 = musical key (music-theory term, not casual 키). &quot;BPM 검출&quot; vs &quot;조성 감지&quot; per glossary: 검출 for the technical BPM measurement, 감지 for key detection. 비트 트래킹 / 샘플 / 슬라이서 / 플레이어 / 건반 kept in Hangul per glossary; BPM, Chroma, format codes kept Latin. 해요체 throughout. Flag for native review.</translatorcomment>
        <translation>오디오 파일을 분석해 BPM과 조성을 감지해요.
결과는 하모닉 믹싱에 편리한 하모닉 키 코드로 표시돼요.

기능:
  - 실행 취소가 가능한 일괄 파일 이름 변경
  - 메타데이터 편집
  - 샘플 추출을 위한 슬라이서 내장 플레이어
  - 하모닉 건반
  - 비트 트래킹을 이용한 BPM 검출
  - Chroma 분석을 이용한 조성 감지
  - 스펙트럼 분석기</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/about_dialog.py" line="208"/>
        <source>Supported formats: MP3, WAV, FLAC, AIFF, M4A, OGG</source>
        <translation>지원 형식: MP3, WAV, FLAC, AIFF, M4A, OGG</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/about_dialog.py" line="227"/>
        <source>Find Your Way Around</source>
        <translatorcomment>Section heading → noun phrase &quot;둘러보기&quot; (Apple-style &quot;take a look around&quot;). Flag for native review.</translatorcomment>
        <translation>둘러보기</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/about_dialog.py" line="240"/>
        <source>&lt;div style=&quot;color: {p}; font-size: 13px; line-height: 1.6; text-align: center;&quot;&gt;Drop your files onto any panel to get started.&lt;br&gt;The sidebar isn&apos;t just for navigation — you can&lt;br&gt;drag files right onto the buttons to route them.&lt;br&gt;&lt;br&gt;&lt;span style=&quot;color: {y}; font-weight: bold;&quot;&gt;RENAME&lt;/span&gt; — Clean up filenames first&lt;br&gt;&lt;span style=&quot;color: {s};&quot;&gt;trim, prefix, preview before you commit&lt;/span&gt;&lt;br&gt;&lt;span style=&quot;color: {s};&quot;&gt;↓&lt;/span&gt;&lt;br&gt;&lt;span style=&quot;color: {y}; font-weight: bold;&quot;&gt;ANALYZE&lt;/span&gt; — Detects BPM, key &amp;amp; energy&lt;br&gt;&lt;span style=&quot;color: {s};&quot;&gt;auto-writes tags + renames in one shot&lt;/span&gt;&lt;br&gt;&lt;span style=&quot;color: {s};&quot;&gt;↓&lt;/span&gt;&lt;br&gt;&lt;span style=&quot;color: {y}; font-weight: bold;&quot;&gt;CONVERT&lt;/span&gt; — Flip formats&lt;br&gt;&lt;span style=&quot;color: {s};&quot;&gt;WAV ↔ FLAC ↔ AIFF ↔ MP3&lt;/span&gt;&lt;br&gt;&lt;br&gt;Use &lt;span style=&quot;color: {y};&quot;&gt;Send To&lt;/span&gt; to move files between panels.&lt;/div&gt;</source>
        <translatorcomment>HTML markup, {p}/{y}/{s} color placeholders and arrows preserved verbatim. Panel names rendered as the localized panel terms (이름 변경 / 분석 / 변환) used in the sidebar; &quot;Send To&quot; → 보내기. 해요체. Flag for native review (spacing + HTML integrity).</translatorcomment>
        <translation>&lt;div style=&quot;color: {p}; font-size: 13px; line-height: 1.6; text-align: center;&quot;&gt;파일을 아무 패널에나 끌어다 놓으면 시작돼요.&lt;br&gt;사이드바는 탐색만을 위한 것이 아니에요 — 버튼 위로&lt;br&gt;파일을 끌어다 놓아 원하는 패널로 보낼 수 있어요.&lt;br&gt;&lt;br&gt;&lt;span style=&quot;color: {y}; font-weight: bold;&quot;&gt;이름 변경&lt;/span&gt; — 먼저 파일명을 정리해요&lt;br&gt;&lt;span style=&quot;color: {s};&quot;&gt;다듬기, 접두사 추가, 적용 전 미리 보기&lt;/span&gt;&lt;br&gt;&lt;span style=&quot;color: {s};&quot;&gt;↓&lt;/span&gt;&lt;br&gt;&lt;span style=&quot;color: {y}; font-weight: bold;&quot;&gt;분석&lt;/span&gt; — BPM, 조성, 에너지를 감지해요&lt;br&gt;&lt;span style=&quot;color: {s};&quot;&gt;태그 자동 기록 + 이름 변경을 한 번에&lt;/span&gt;&lt;br&gt;&lt;span style=&quot;color: {s};&quot;&gt;↓&lt;/span&gt;&lt;br&gt;&lt;span style=&quot;color: {y}; font-weight: bold;&quot;&gt;변환&lt;/span&gt; — 형식을 바꿔요&lt;br&gt;&lt;span style=&quot;color: {s};&quot;&gt;WAV ↔ FLAC ↔ AIFF ↔ MP3&lt;/span&gt;&lt;br&gt;&lt;br&gt;패널 간에 파일을 옮기려면 &lt;span style=&quot;color: {y};&quot;&gt;보내기&lt;/span&gt;를 사용해요.&lt;/div&gt;</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/about_dialog.py" line="341"/>
        <source>click for more</source>
        <translatorcomment>Compact hint → noun phrase &quot;자세히 보기&quot; (see more), avoiding an imperative. Flag for native review.</translatorcomment>
        <translation>자세히 보기</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/about_dialog.py" line="362"/>
        <source>Checking…</source>
        <translation>확인 중…</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/about_dialog.py" line="386"/>
        <source>You&apos;re on the latest version</source>
        <translation>최신 버전을 사용 중입니다</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/about_dialog.py" line="390"/>
        <source>Download</source>
        <translation>다운로드</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/about_dialog.py" line="391"/>
        <source>Update available: {0}</source>
        <translation>업데이트가 있습니다: {0}</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/about_dialog.py" line="399"/>
        <source>see all releases</source>
        <translation>모든 릴리스 보기</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/about_dialog.py" line="400"/>
        <source>Couldn&apos;t check for updates</source>
        <translation>업데이트를 확인할 수 없습니다</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/about_dialog.py" line="286"/>
        <source>The Rest of the Kit</source>
        <translatorcomment>Section heading → noun phrase &quot;나머지 기능&quot; (the rest of the features). Flag for native review.</translatorcomment>
        <translation>나머지 기능</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/about_dialog.py" line="296"/>
        <source>&lt;div style=&quot;color: {p}; font-size: 13px; line-height: 1.7; text-align: center;&quot;&gt;&lt;span style=&quot;color: {y}; font-weight: bold;&quot;&gt;SLICE&lt;/span&gt; — Grab a section from any track.&lt;br&gt;&lt;span style=&quot;color: {s};&quot;&gt;Open from inside Player window.&lt;br&gt;Set start/end with the range slider or mark&lt;br&gt;boundaries from playback. Nudge ±10ms.&lt;/span&gt;&lt;br&gt;&lt;br&gt;&lt;span style=&quot;color: {y}; font-weight: bold;&quot;&gt;METADATA&lt;/span&gt; — Drop a file in, edit its tags.&lt;br&gt;&lt;span style=&quot;color: {s};&quot;&gt;Auto-saves when you move on.&lt;/span&gt;&lt;br&gt;&lt;br&gt;&lt;span style=&quot;color: {y}; font-weight: bold;&quot;&gt;KEYBOARD&lt;/span&gt; — Play notes in any key.&lt;br&gt;&lt;span style=&quot;color: {s};&quot;&gt;Harmonic key strip right there for reference.&lt;/span&gt;&lt;br&gt;&lt;br&gt;&lt;span style=&quot;color: {y}; font-weight: bold;&quot;&gt;SPECTRUM&lt;/span&gt; — Acoustic spectrum analyzer.&lt;br&gt;&lt;span style=&quot;color: {s};&quot;&gt;Visual representation of audio quality.&lt;/span&gt;&lt;br&gt;&lt;br&gt;&lt;span style=&quot;color: {y}; font-weight: bold;&quot;&gt;SETTINGS&lt;/span&gt; — BPM range, key format,&lt;br&gt;&lt;span style=&quot;color: {s};&quot;&gt;auto-rename rules.&lt;/span&gt;&lt;/div&gt;</source>
        <translatorcomment>HTML/placeholders preserved. SLICE → 자르기, KEYBOARD → 건반 (musical keyboard, not 키보드), &quot;in any key&quot; → 조성, &quot;key format&quot; → 조성 형식. 플레이어/슬라이서 in Hangul. 해요체. Flag for native review.</translatorcomment>
        <translation>&lt;div style=&quot;color: {p}; font-size: 13px; line-height: 1.7; text-align: center;&quot;&gt;&lt;span style=&quot;color: {y}; font-weight: bold;&quot;&gt;자르기&lt;/span&gt; — 트랙에서 원하는 구간을 잡아내요.&lt;br&gt;&lt;span style=&quot;color: {s};&quot;&gt;플레이어 창 안에서 열어요.&lt;br&gt;범위 슬라이더로 시작/끝을 설정하거나 재생 중에&lt;br&gt;경계를 표시해요. ±10ms 단위로 미세 조정해요.&lt;/span&gt;&lt;br&gt;&lt;br&gt;&lt;span style=&quot;color: {y}; font-weight: bold;&quot;&gt;메타데이터&lt;/span&gt; — 파일을 끌어다 놓고 태그를 편집해요.&lt;br&gt;&lt;span style=&quot;color: {s};&quot;&gt;다른 곳으로 이동하면 자동 저장돼요.&lt;/span&gt;&lt;br&gt;&lt;br&gt;&lt;span style=&quot;color: {y}; font-weight: bold;&quot;&gt;건반&lt;/span&gt; — 원하는 조성으로 음을 연주해요.&lt;br&gt;&lt;span style=&quot;color: {s};&quot;&gt;참고용 하모닉 키 스트립이 바로 옆에 있어요.&lt;/span&gt;&lt;br&gt;&lt;br&gt;&lt;span style=&quot;color: {y}; font-weight: bold;&quot;&gt;스펙트럼&lt;/span&gt; — 음향 스펙트럼 분석기.&lt;br&gt;&lt;span style=&quot;color: {s};&quot;&gt;오디오 품질을 시각적으로 표현해요.&lt;/span&gt;&lt;br&gt;&lt;br&gt;&lt;span style=&quot;color: {y}; font-weight: bold;&quot;&gt;설정&lt;/span&gt; — BPM 범위, 조성 형식,&lt;br&gt;&lt;span style=&quot;color: {s};&quot;&gt;자동 이름 변경 규칙.&lt;/span&gt;&lt;/div&gt;</translation>
    </message>
</context>
<context>
    <name>AnalysisPanel</name>
    <message>
        <location filename="../widgets/analysis_panel.py" line="201"/>
        <location filename="../widgets/analysis_panel.py" line="280"/>
        <source>Analyze</source>
        <translatorcomment>Dual-use as panel title and action button → bare noun 분석 (works for both); &quot;분석하기&quot; would read oddly as a title. Flag for native review.</translatorcomment>
        <translation>분석</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="204"/>
        <source>Drop files to analyze, unless changed in settings. Results update in real-time.</source>
        <translatorcomment>해요체 descriptive sentence. &quot;unless changed in settings&quot; rendered as &quot;설정에서 변경한 경우는 예외예요&quot;. Flag for native review (phrasing + spacing).</translatorcomment>
        <translation>파일을 끌어다 놓으면 분석해요. 설정에서 변경한 경우는 예외예요. 결과는 실시간으로 업데이트돼요.</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="211"/>
        <source>Auto</source>
        <translation>자동</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="217"/>
        <source>Auto-analyze when dropping or sending to the Analyze panel</source>
        <translatorcomment>Checkbox label → noun phrase. &quot;sending&quot; refers to the Send To (보내기) routing. Flag for native review.</translatorcomment>
        <translation>분석 패널에 끌어다 놓거나 보낼 때 자동 분석</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="230"/>
        <source>Drop files here to analyze immediately</source>
        <translation>여기에 끌어다 놓으면 바로 분석해요</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="276"/>
        <source>Clear Results</source>
        <translatorcomment>Action button → -기 nominalization (지우기) per Apple Korean UI convention.</translatorcomment>
        <translation>결과 지우기</translation>
    </message>
    <message>
        <source>Remove Selected</source>
        <translation type="vanished">선택 항목 제거</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="287"/>
        <source>Send To</source>
        <translatorcomment>Localized per CLAUDE.md (not left as a Latin island). 보내기 = Apple Korean nominalized form.</translatorcomment>
        <translation>보내기</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="289"/>
        <source>Convert</source>
        <translation>변환</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="290"/>
        <source>Player</source>
        <translatorcomment>플레이어 (Hangul loanword) per glossary.</translatorcomment>
        <translation>플레이어</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="362"/>
        <source>{n} analyzed</source>
        <translatorcomment>Counter 개 for files. &quot;분석됨&quot; passive. Flag counter choice for native review.</translatorcomment>
        <translation>{n}개 분석됨</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="364"/>
        <source>{n} errors</source>
        <translation>오류 {n}개</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="366"/>
        <source>{n} pending</source>
        <translation>대기 중 {n}개</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="368"/>
        <source>{n} in progress</source>
        <translation>진행 중 {n}개</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="370"/>
        <source>No results yet</source>
        <translation>아직 결과가 없어요</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="426"/>
        <source>Open File Location</source>
        <translation>파일 위치 열기</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="428"/>
        <source>Remove</source>
        <translation>제거</translation>
    </message>
</context>
<context>
    <name>AnalysisTableModel</name>
    <message>
        <location filename="../widgets/analysis_panel.py" line="36"/>
        <source>Name</source>
        <translation>이름</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="37"/>
        <source>BPM</source>
        <translation>BPM</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="38"/>
        <location filename="../widgets/analysis_panel.py" line="40"/>
        <source>Conf</source>
        <translatorcomment>&quot;Conf&quot; = confidence → 신뢰도. Column header; longer than the English abbreviation — verify it fits the column width. Flag for native review.</translatorcomment>
        <translation>신뢰도</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="39"/>
        <source>Key</source>
        <translatorcomment>조성 = musical key (music-theory term, not casual 키). Column shows the detected key. Flag for native review.</translatorcomment>
        <translation>조성</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="41"/>
        <source>Key Code</source>
        <translatorcomment>The harmonic key-code label → 키 코드 (Hangul). Distinct from 조성 (the musical key itself).</translatorcomment>
        <translation>키 코드</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="42"/>
        <source>Alt Keys</source>
        <translation>대체 조성</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="43"/>
        <source>Energy</source>
        <translation>에너지</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="44"/>
        <source>Status</source>
        <translation>상태</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="86"/>
        <source>Other likely keys: {keys}</source>
        <translation>가능성 있는 다른 조성: {keys}</translation>
    </message>
</context>
<context>
    <name>ArtworkWidget</name>
    <message>
        <location filename="../widgets/artwork_widget.py" line="54"/>
        <location filename="../widgets/artwork_widget.py" line="112"/>
        <source>No artwork

Drop an image here
or click “Add Artwork…”</source>
        <translatorcomment>artwork → 아트워크. Curly quotes from source preserved. 해요체 imperative (놓거나/클릭하세요). Flag for native review.</translatorcomment>
        <translation>아트워크 없음

여기에 이미지를 끌어다 놓거나
“아트워크 추가…”를 클릭하세요</translation>
    </message>
</context>
<context>
    <name>ConversionPanel</name>
    <message>
        <location filename="../widgets/conversion_panel.py" line="66"/>
        <location filename="../widgets/conversion_panel.py" line="176"/>
        <source>Convert</source>
        <translatorcomment>Dual-use title/button → bare noun 변환.</translatorcomment>
        <translation>변환</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="69"/>
        <source>Convert audio files between formats (WAV, FLAC, AIFF, MP3).</source>
        <translation>오디오 파일을 다른 형식으로 변환해요 (WAV, FLAC, AIFF, MP3).</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="75"/>
        <source>Target Format:</source>
        <translation>대상 형식:</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="82"/>
        <source>Sample Rate:</source>
        <translatorcomment>DSP term &quot;sample rate&quot; (not the producer &quot;sample&quot;) → 샘플 레이트, the standard loanword in Korean audio software. Flag for native review.</translatorcomment>
        <translation>샘플 레이트:</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="85"/>
        <source>96 kHz (DVD)</source>
        <translation>96 kHz (DVD)</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="86"/>
        <source>48 kHz (DAT)</source>
        <translation>48 kHz (DAT)</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="87"/>
        <source>44.1 kHz (CD)</source>
        <translation>44.1 kHz (CD)</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="88"/>
        <source>32 kHz</source>
        <translation>32 kHz</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="98"/>
        <source>Bit Depth:</source>
        <translatorcomment>bit depth → 비트 심도 (standard Korean DSP term).</translatorcomment>
        <translation>비트 심도:</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="101"/>
        <source>32 bit</source>
        <translation>32비트</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="102"/>
        <source>24 bit (DVD)</source>
        <translation>24비트 (DVD)</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="103"/>
        <source>16 bit (CD)</source>
        <translation>16비트 (CD)</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="104"/>
        <source>8 bit</source>
        <translation>8비트</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="114"/>
        <source>Bitrate:</source>
        <translation>비트레이트:</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="134"/>
        <source>Files</source>
        <translatorcomment>파일 (Hangul) per glossary — Apple Korean Finder standard, never 문서.</translatorcomment>
        <translation>파일</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="137"/>
        <source>Drop audio files here to add them</source>
        <translation>오디오 파일을 여기에 끌어다 놓으면 추가돼요</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="140"/>
        <source>Filename</source>
        <translation>파일명</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="141"/>
        <source>From</source>
        <translatorcomment>Column = source format → 원본 (rather than literal &quot;~에서&quot;). Pairs with 대상 below. Flag for native review.</translatorcomment>
        <translation>원본</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="142"/>
        <source>To</source>
        <translatorcomment>Column = target format → 대상. Pairs with 원본 above.</translatorcomment>
        <translation>대상</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="143"/>
        <source>Status</source>
        <translation>상태</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="170"/>
        <location filename="../widgets/conversion_panel.py" line="488"/>
        <source>No files</source>
        <translation>파일 없음</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="183"/>
        <source>Send To</source>
        <translation>보내기</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="185"/>
        <source>Select at least one file to send.</source>
        <translation>보낼 파일을 하나 이상 선택하세요.</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="187"/>
        <source>Analyze</source>
        <translation>분석</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="188"/>
        <source>Rename</source>
        <translatorcomment>이름 변경 = Apple Korean Finder term for Rename.</translatorcomment>
        <translation>이름 변경</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="189"/>
        <source>Player</source>
        <translation>플레이어</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="198"/>
        <source>Lossy files not allowed</source>
        <translatorcomment>lossy → 손실 (audio term). Flag for native review.</translatorcomment>
        <translation>손실 파일은 허용되지 않아요</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="373"/>
        <source>Open File Location</source>
        <translation>파일 위치 열기</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="375"/>
        <source>Remove</source>
        <translation>제거</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="456"/>
        <location filename="../widgets/conversion_panel.py" line="646"/>
        <source>Done</source>
        <translation>완료</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="465"/>
        <source>Same format</source>
        <translation>동일한 형식</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="472"/>
        <location filename="../widgets/conversion_panel.py" line="638"/>
        <location filename="../widgets/conversion_panel.py" line="668"/>
        <source>Ready</source>
        <translation>준비됨</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="483"/>
        <source>{count} files</source>
        <translation>파일 {count}개</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="485"/>
        <source>{count} to convert</source>
        <translation>변환 대상 {count}개</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="487"/>
        <source>({count} lossy skipped)</source>
        <translation>(손실 {count}개 건너뜀)</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="610"/>
        <source>Converting</source>
        <translation>변환 중</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="631"/>
        <source>Incomplete</source>
        <translation>미완료</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="631"/>
        <source>Error</source>
        <translation>오류</translation>
    </message>
</context>
<context>
    <name>DropZone</name>
    <message>
        <location filename="../widgets/drop_zone.py" line="29"/>
        <source>Drag and drop audio files here</source>
        <translation>오디오 파일을 여기에 끌어다 놓으세요</translation>
    </message>
    <message>
        <location filename="../widgets/drop_zone.py" line="42"/>
        <source>MP3, WAV, FLAC, AIFF, M4A, OGG</source>
        <translation>MP3, WAV, FLAC, AIFF, M4A, OGG</translation>
    </message>
</context>
<context>
    <name>HeaderBar</name>
    <message>
        <location filename="../widgets/header_bar.py" line="59"/>
        <source>DJ Audio Analysis Toolkit</source>
        <translation>DJ 오디오 분석 툴킷</translation>
    </message>
    <message>
        <location filename="../widgets/header_bar.py" line="71"/>
        <source>Add</source>
        <translation>추가</translation>
    </message>
    <message>
        <location filename="../widgets/header_bar.py" line="77"/>
        <source>Add files or a folder to the panel you&apos;re currently viewing</source>
        <translation>현재 보고 있는 패널에 파일 또는 폴더를 추가합니다</translation>
    </message>
    <message>
        <location filename="../widgets/header_bar.py" line="81"/>
        <source>Files…</source>
        <translation>파일…</translation>
    </message>
    <message>
        <location filename="../widgets/header_bar.py" line="82"/>
        <source>Folder…</source>
        <translation>폴더…</translation>
    </message>
    <message>
        <source>Add Files</source>
        <translation type="vanished">파일 추가</translation>
    </message>
    <message>
        <source>Adds files to the panel you&apos;re currently viewing</source>
        <translation type="vanished">현재 보고 있는 패널에 파일을 추가합니다</translation>
    </message>
    <message>
        <source>Add Folder</source>
        <translation type="vanished">폴더 추가</translation>
    </message>
    <message>
        <source>Adds a folder&apos;s files to the panel you&apos;re currently viewing</source>
        <translation type="vanished">현재 보고 있는 패널에 폴더의 파일을 추가합니다</translation>
    </message>
</context>
<context>
    <name>HistoryPanel</name>
    <message>
        <location filename="../widgets/history_panel.py" line="156"/>
        <location filename="../widgets/history_panel.py" line="377"/>
        <source>Rename History</source>
        <translatorcomment>History → 기록 (more native/polished than the loanword 히스토리), per glossary. Flag for native review.</translatorcomment>
        <translation>이름 변경 기록</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="160"/>
        <location filename="../widgets/history_panel.py" line="379"/>
        <source>View recent rename operations. Select a session to undo it.</source>
        <translatorcomment>Undo → 실행 취소 (Apple/MS/Samsung Korean standard). 해요체.</translatorcomment>
        <translation>최근 이름 변경 작업을 확인해요. 실행을 취소하려면 세션을 선택하세요.</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="174"/>
        <source>Session ID</source>
        <translation>세션 ID</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="174"/>
        <location filename="../widgets/history_panel.py" line="212"/>
        <source>Date/Time</source>
        <translation>날짜/시간</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="174"/>
        <source>Files</source>
        <translation>파일</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="174"/>
        <source>Description</source>
        <translation>설명</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="204"/>
        <source>Name</source>
        <translation>이름</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="205"/>
        <source>BPM</source>
        <translation>BPM</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="206"/>
        <location filename="../widgets/history_panel.py" line="208"/>
        <source>Conf</source>
        <translation>신뢰도</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="207"/>
        <source>Key</source>
        <translation>조성</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="209"/>
        <source>Key Code</source>
        <translation>키 코드</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="210"/>
        <source>Alt Keys</source>
        <translation>대체 조성</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="211"/>
        <source>Energy</source>
        <translation>에너지</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="260"/>
        <location filename="../widgets/history_panel.py" line="563"/>
        <source>{0} Rename Sessions</source>
        <translation>이름 변경 세션 {0}개</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="267"/>
        <location filename="../widgets/history_panel.py" line="508"/>
        <source>{0} Song Keys</source>
        <translation>곡 조성 {0}개</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="285"/>
        <source>Show</source>
        <translation>표시</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="307"/>
        <location filename="../widgets/history_panel.py" line="723"/>
        <location filename="../widgets/history_panel.py" line="736"/>
        <source>Export CSV</source>
        <translation>CSV 내보내기</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="309"/>
        <source>Export the table below to a spreadsheet-friendly CSV file.</source>
        <translation>아래 표를 스프레드시트에서 열 수 있는 CSV 파일로 내보냅니다.</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="422"/>
        <source>Low confidence — this key is worth double-checking.</source>
        <translation>신뢰도가 낮습니다. 이 키는 다시 확인하는 것이 좋습니다.</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="425"/>
        <source>Low confidence — the tempo may be half or double time.</source>
        <translation>신뢰도가 낮습니다. 템포가 절반 또는 두 배일 수 있습니다.</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="620"/>
        <location filename="../widgets/history_panel.py" line="635"/>
        <source>Open File Location</source>
        <translation>파일 위치 열기</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="637"/>
        <source>This file can&apos;t be found — it may have been moved, renamed, or deleted.</source>
        <translation>파일을 찾을 수 없습니다. 이동, 이름 변경 또는 삭제되었을 수 있습니다.</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="724"/>
        <source>There is nothing to export yet.</source>
        <translation>아직 내보낼 항목이 없습니다.</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="746"/>
        <source>Export failed</source>
        <translation>내보내기 실패</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="747"/>
        <source>Could not write the file:
{0}</source>
        <translation>파일을 쓸 수 없습니다:
{0}</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="753"/>
        <source>Export complete</source>
        <translation>내보내기 완료</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="754"/>
        <source>Exported {0} rows to:
{1}</source>
        <translation>{0}개 행을 내보냈습니다:
{1}</translation>
    </message>
    <message>
        <source>0 sessions</source>
        <translation type="vanished">세션 0개</translation>
    </message>
    <message>
        <source>Refresh</source>
        <translatorcomment>새로 고침 = Apple Korean standard (with space).</translatorcomment>
        <translation type="vanished">새로 고침</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="317"/>
        <source>Delete</source>
        <translation>삭제</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="322"/>
        <source>Undo Selected</source>
        <translation>선택 항목 실행 취소</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="372"/>
        <source>Key History</source>
        <translation>조성 기록</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="374"/>
        <source>Recently analyzed tracks and their detected keys.</source>
        <translation>최근 분석한 트랙과 감지된 조성입니다.</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="553"/>
        <source>Renamed {0} files: {1}</source>
        <translation>파일 {0}개 이름 변경 완료: {1}</translation>
    </message>
    <message>
        <source>Renamed {0} files</source>
        <translation type="vanished">파일 {0}개 이름 변경 완료</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="557"/>
        <source>No description</source>
        <translation>설명 없음</translation>
    </message>
    <message>
        <source>{0} sessions</source>
        <translation type="vanished">세션 {0}개</translation>
    </message>
</context>
<context>
    <name>KeyInfoBox</name>
    <message>
        <location filename="../widgets/key_info_box.py" line="109"/>
        <source>Press a key to see harmonic info…</source>
        <translatorcomment>&quot;a key&quot; here = a piano key → 건반 (not 키, not 조성). harmonic → 하모닉. 해요체 imperative. Flag for native review.</translatorcomment>
        <translation>하모닉 정보를 보려면 건반을 누르세요…</translation>
    </message>
    <message>
        <location filename="../widgets/key_info_box.py" line="124"/>
        <source>NOTATION</source>
        <translation>표기법</translation>
    </message>
    <message>
        <location filename="../widgets/key_info_box.py" line="125"/>
        <source>MINOR</source>
        <translatorcomment>Mode label for the key → 단조 (minor key, music-theory term). Distinct from the &quot;마이너 코드&quot; chord button. Flag for native review.</translatorcomment>
        <translation>단조</translation>
    </message>
    <message>
        <location filename="../widgets/key_info_box.py" line="126"/>
        <source>MAJOR</source>
        <translatorcomment>Mode label for the key → 장조 (major key, music-theory term). Flag for native review.</translatorcomment>
        <translation>장조</translation>
    </message>
    <message>
        <location filename="../widgets/key_info_box.py" line="146"/>
        <source>COMPATIBLE WITH</source>
        <translatorcomment>&quot;Compatible with&quot; (harmonically compatible keys) → 호환되는 조성. Flag for native review.</translatorcomment>
        <translation>호환되는 조성</translation>
    </message>
</context>
<context>
    <name>KeyboardPanel</name>
    <message>
        <location filename="../widgets/keyboard_panel.py" line="582"/>
        <source>Keyboard</source>
        <translatorcomment>The piano panel → 건반 (musical keyboard), NOT 키보드 (computer keyboard), per glossary.</translatorcomment>
        <translation>건반</translation>
    </message>
    <message>
        <location filename="../widgets/keyboard_panel.py" line="585"/>
        <source>Play chords to compare musical keys. Click keys or use QWERTY shortcuts (A-J, K-L-;). Z/X to shift octave.</source>
        <translatorcomment>chords → 코드, musical keys → 조성, &quot;keys&quot; (the things you click) → 건반, octave → 옥타브. QWERTY/letter shortcuts kept Latin. 해요체. Flag for native review.</translatorcomment>
        <translation>코드를 연주해 조성을 비교해요. 건반을 클릭하거나 QWERTY 단축키(A–J, K–L–;)를 사용하세요. Z/X로 옥타브를 이동해요.</translation>
    </message>
    <message>
        <location filename="../widgets/keyboard_panel.py" line="595"/>
        <source>Notation can be changed in settings</source>
        <translation>표기법은 설정에서 변경할 수 있습니다</translation>
    </message>
    <message>
        <location filename="../widgets/keyboard_panel.py" line="609"/>
        <source>Minor Chord</source>
        <translatorcomment>Chord button → 마이너 코드 (producer-context loanword, widely used). Note: distinct from the mode label 단조. Flag for native review.</translatorcomment>
        <translation>마이너 코드</translation>
    </message>
    <message>
        <location filename="../widgets/keyboard_panel.py" line="610"/>
        <source>Major Chord</source>
        <translatorcomment>Chord button → 메이저 코드 (producer-context loanword). Flag for native review.</translatorcomment>
        <translation>메이저 코드</translation>
    </message>
    <message>
        <location filename="../widgets/keyboard_panel.py" line="677"/>
        <source>View</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <location filename="../widgets/keyboard_panel.py" line="682"/>
        <source>Circle of Fifths</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <location filename="../widgets/keyboard_panel.py" line="681"/>
        <source>Hex Grid</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <location filename="../widgets/keyboard_panel.py" line="845"/>
        <location filename="../widgets/keyboard_panel.py" line="848"/>
        <source>👑 Key Codes</source>
        <translation>👑 키 코드</translation>
    </message>
    <message>
        <location filename="../widgets/keyboard_panel.py" line="846"/>
        <source>Traditional Key Notation</source>
        <translatorcomment>&quot;Traditional key notation&quot; → 전통 조성 표기 (key → 조성, notation → 표기). Flag for native review.</translatorcomment>
        <translation>전통 조성 표기</translation>
    </message>
    <message>
        <location filename="../widgets/keyboard_panel.py" line="847"/>
        <source>Traktor Open Key</source>
        <translatorcomment>Proper name of Traktor&apos;s notation system — kept in English (product term). Flag for native review.</translatorcomment>
        <translation>Traktor Open Key</translation>
    </message>
</context>
<context>
    <name>MainWindow</name>
    <message>
        <location filename="../main_window.py" line="70"/>
        <source>Mixed in P</source>
        <translation>Mixed in P</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="322"/>
        <source>Select Audio Files</source>
        <translation>오디오 파일 선택</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="333"/>
        <source>Select Folder</source>
        <translation>폴더 선택</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="420"/>
        <source>No Audio Files</source>
        <translation>오디오 파일 없음</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="421"/>
        <source>No audio files found in:
{0}</source>
        <translation>다음 위치에서 오디오 파일을 찾을 수 없어요:
{0}</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="426"/>
        <source>Invalid Folder</source>
        <translation>잘못된 폴더</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="427"/>
        <source>Not a valid directory:
{0}</source>
        <translatorcomment>directory → 디렉터리 (Apple Korean spelling). Flag for native review.</translatorcomment>
        <translation>유효한 디렉터리가 아니에요:
{0}</translation>
    </message>
    <message>
        <source>Analysis in Progress</source>
        <translation type="vanished">분석 진행 중</translation>
    </message>
    <message>
        <source>An analysis is already running. Please wait or cancel it first.</source>
        <translation type="vanished">이미 분석이 실행 중이에요. 잠시 기다리거나 먼저 취소하세요.</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="525"/>
        <source>Analyzing...</source>
        <translation>분석 중...</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="550"/>
        <source>Complete: {0} analyzed, {1} errors</source>
        <translation>완료: {0}개 분석, 오류 {1}개</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="554"/>
        <source>Complete: {0} files analyzed</source>
        <translation>완료: 파일 {0}개 분석</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="594"/>
        <source>Cancelled</source>
        <translation>취소됨</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="681"/>
        <source>Conversion in Progress</source>
        <translation>변환 진행 중</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="682"/>
        <source>A conversion is already running. Please wait.</source>
        <translation>이미 변환이 실행 중이에요. 잠시 기다리세요.</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="712"/>
        <source>Converting...</source>
        <translation>변환 중...</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="728"/>
        <source>Complete: {0} converted, {1} errors</source>
        <translation>완료: {0}개 변환, 오류 {1}개</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="732"/>
        <source>Complete: {0} files converted</source>
        <translation>완료: 파일 {0}개 변환</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="901"/>
        <source>Rename in Progress</source>
        <translation>이름 변경 진행 중</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="902"/>
        <source>A rename operation is already running.</source>
        <translation>이미 이름 변경 작업이 실행 중이에요.</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="951"/>
        <source>Rename Failed</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <location filename="../main_window.py" line="985"/>
        <source>Undo Rename</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <location filename="../main_window.py" line="1008"/>
        <source>Undo Failed</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Renaming files...</source>
        <translation type="vanished">파일 이름 변경 중...</translation>
    </message>
    <message>
        <source>Renamed {0} files</source>
        <translation type="vanished">파일 {0}개 이름 변경 완료</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="957"/>
        <source>No Session</source>
        <translation>세션 없음</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="957"/>
        <source>No rename session to undo.</source>
        <translation>실행 취소할 이름 변경 세션이 없어요.</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="966"/>
        <source>Confirm Undo</source>
        <translation>실행 취소 확인</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="967"/>
        <source>Undo renaming of {0} files?</source>
        <translatorcomment>Object particle avoided via 의 + 을 on 이름 변경. Counter 개. Flag for native review.</translatorcomment>
        <translation>파일 {0}개의 이름 변경을 실행 취소할까요?</translation>
    </message>
    <message>
        <source>Undoing rename...</source>
        <translation type="vanished">이름 변경 실행 취소 중...</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="986"/>
        <source>Undone: {0} files, {1} errors</source>
        <translation>실행 취소: 파일 {0}개, 오류 {1}개</translation>
    </message>
    <message>
        <source>Undone {0} files</source>
        <translation type="vanished">파일 {0}개 실행 취소 완료</translation>
    </message>
</context>
<context>
    <name>MetadataPanel</name>
    <message>
        <location filename="../widgets/metadata_panel.py" line="43"/>
        <source>Title</source>
        <translation>제목</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="44"/>
        <source>Artist</source>
        <translation>아티스트</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="45"/>
        <source>Album</source>
        <translation>앨범</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="46"/>
        <source>Label</source>
        <translation>레이블</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="47"/>
        <source>Genre</source>
        <translation>장르</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="48"/>
        <source>BPM</source>
        <translation>BPM</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="49"/>
        <source>Key</source>
        <translatorcomment>Metadata tag for the musical key → 조성. Flag for native review.</translatorcomment>
        <translation>조성</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="50"/>
        <source>Year</source>
        <translation>연도</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="51"/>
        <source>Track #</source>
        <translatorcomment>Track → 트랙 (music-production context). &quot;Track #&quot; → 트랙 번호.</translatorcomment>
        <translation>트랙 번호</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="52"/>
        <source>Comment</source>
        <translatorcomment>ID3 comment tag → 코멘트 (loanword DJs recognize); used consistently with the Settings &quot;Comment tag&quot; strings. Flag for native review (vs 설명).</translatorcomment>
        <translation>코멘트</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="111"/>
        <source>Metadata Editor</source>
        <translation>메타데이터 편집기</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="114"/>
        <source>Drop a single audio file to view and edit its metadata tags.</source>
        <translation>오디오 파일 하나를 끌어다 놓으면 메타데이터 태그를 보고 편집할 수 있어요.</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="185"/>
        <location filename="../widgets/metadata_panel.py" line="305"/>
        <source>Add field...</source>
        <translation>필드 추가...</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="190"/>
        <source>Add Artwork…</source>
        <translation>아트워크 추가…</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="195"/>
        <source>Remove</source>
        <translation>제거</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="214"/>
        <source>Reload</source>
        <translation>다시 불러오기</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="219"/>
        <source>Eject</source>
        <translatorcomment>Eject → 꺼내기 (Apple Korean). Flag for native review.</translatorcomment>
        <translation>꺼내기</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="273"/>
        <source>Error: {0}</source>
        <translation>오류: {0}</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="484"/>
        <source>Select cover art</source>
        <translation>커버 아트 선택</translation>
    </message>
</context>
<context>
    <name>PlayerPanel</name>
    <message>
        <location filename="../widgets/player_panel.py" line="1022"/>
        <source>Player</source>
        <translation>플레이어</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1043"/>
        <source>Choose a visualization</source>
        <translation>시각 효과 선택</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1051"/>
        <source>Visuals off</source>
        <translation>시각 효과 끔</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1052"/>
        <source>Backdrop waveform</source>
        <translation>배경: 파형</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1053"/>
        <source>Backdrop oscilloscope</source>
        <translation>배경: 오실로스코프</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1054"/>
        <source>Backdrop spectrum</source>
        <translation>배경: 스펙트럼</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1055"/>
        <source>Backdrop fire</source>
        <translation>배경: 불꽃</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1056"/>
        <source>Backdrop fractal</source>
        <translation>배경: 프랙털</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1057"/>
        <source>Popout oscilloscope</source>
        <translation>별도 창: 오실로스코프</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1058"/>
        <source>Popout spectrum bars</source>
        <translation>별도 창: 스펙트럼 막대</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1059"/>
        <source>Popout fire</source>
        <translation>별도 창: 불꽃</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1060"/>
        <source>Popout fractal</source>
        <translation>별도 창: 프랙털</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1080"/>
        <source>Edit Lock</source>
        <translation>편집 잠금</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1084"/>
        <source>Lock metadata editing in the playlist</source>
        <translation>재생목록의 메타데이터 편집 잠금</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1097"/>
        <source>#</source>
        <translation>#</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1098"/>
        <source>Filename</source>
        <translation>파일명</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1099"/>
        <source>Artist</source>
        <translation>아티스트</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1100"/>
        <source>Title</source>
        <translation>제목</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1101"/>
        <source>BPM</source>
        <translation>BPM</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1102"/>
        <source>Key</source>
        <translatorcomment>Playlist column for the musical key → 조성. Flag for native review.</translatorcomment>
        <translation>조성</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1103"/>
        <source>Comment</source>
        <translation>코멘트</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1104"/>
        <source>Duration</source>
        <translatorcomment>Duration → 재생 시간 (playback length).</translatorcomment>
        <translation>재생 시간</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1105"/>
        <source>Year</source>
        <translation>연도</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1244"/>
        <source>Previous</source>
        <translation>이전</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1255"/>
        <source>Play / Pause  (Space)</source>
        <translatorcomment>Playback → 재생; Pause → 일시정지. Key name &quot;Space&quot; kept Latin.</translatorcomment>
        <translation>재생 / 일시정지  (Space)</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1262"/>
        <source>Stop</source>
        <translation>정지</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1269"/>
        <source>Next</source>
        <translation>다음</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1225"/>
        <source>Vol</source>
        <translatorcomment>Volume abbreviation → 볼륨. Flag for native review (vs 음량).</translatorcomment>
        <translation>볼륨</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1285"/>
        <source>Clear Playlist</source>
        <translatorcomment>playlist → 재생목록; action button → -기 (비우기).</translatorcomment>
        <translation>재생목록 비우기</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1799"/>
        <source>{0} track</source>
        <translatorcomment>Counter for tracks/songs → 곡 per glossary. Korean has no plural; {0} track and {0} tracks render identically. Flag for native review.</translatorcomment>
        <translation>{0}곡</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1801"/>
        <source>{0} tracks</source>
        <translatorcomment>Counter 곡. Same form as the singular (no Korean plural). Flag for native review.</translatorcomment>
        <translation>{0}곡</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="2392"/>
        <source>Open File Location</source>
        <translation>파일 위치 열기</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="2393"/>
        <source>Open in Metadata Panel</source>
        <translation>메타데이터 패널에서 열기</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="2394"/>
        <source>Reload Metadata from File</source>
        <translation>파일에서 메타데이터 다시 불러오기</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="2396"/>
        <source>Remove from Playlist</source>
        <translation>재생목록에서 제거</translation>
    </message>
</context>
<context>
    <name>ProgressPanel</name>
    <message>
        <location filename="../widgets/progress_bar.py" line="41"/>
        <location filename="../widgets/progress_bar.py" line="113"/>
        <source>Analyzing...</source>
        <translation>분석 중...</translation>
    </message>
    <message>
        <location filename="../widgets/progress_bar.py" line="47"/>
        <source>Cancel</source>
        <translation>취소</translation>
    </message>
    <message>
        <location filename="../widgets/progress_bar.py" line="134"/>
        <source>Complete</source>
        <translation>완료</translation>
    </message>
</context>
<context>
    <name>QueuePanel</name>
    <message>
        <location filename="../widgets/queue_panel.py" line="41"/>
        <source>Queue</source>
        <translatorcomment>Queue → 대기열 (standard Korean computing term).</translatorcomment>
        <translation>대기열</translation>
    </message>
    <message>
        <location filename="../widgets/queue_panel.py" line="44"/>
        <source>Add files here to queue them for analysis. Use the buttons below to send them to analysis.</source>
        <translation>여기에 파일을 추가하면 분석 대기열에 들어가요. 아래 버튼으로 분석에 보낼 수 있어요.</translation>
    </message>
    <message>
        <location filename="../widgets/queue_panel.py" line="49"/>
        <source>Drop audio files here to add to queue</source>
        <translation>오디오 파일을 여기에 끌어다 놓으면 대기열에 추가돼요</translation>
    </message>
    <message>
        <location filename="../widgets/queue_panel.py" line="78"/>
        <source>0 files in queue</source>
        <translation>대기열에 파일 0개</translation>
    </message>
    <message>
        <location filename="../widgets/queue_panel.py" line="84"/>
        <source>Clear Queue</source>
        <translation>대기열 비우기</translation>
    </message>
    <message>
        <location filename="../widgets/queue_panel.py" line="88"/>
        <source>Analyze Selected</source>
        <translation>선택 항목 분석</translation>
    </message>
    <message>
        <location filename="../widgets/queue_panel.py" line="92"/>
        <source>Analyze All</source>
        <translation>전체 분석</translation>
    </message>
    <message>
        <location filename="../widgets/queue_panel.py" line="112"/>
        <source>{total} files in queue</source>
        <translation>대기열에 파일 {total}개</translation>
    </message>
    <message>
        <location filename="../widgets/queue_panel.py" line="115"/>
        <source>{queued} queued / {total} total files</source>
        <translation>대기 {queued}개 / 전체 파일 {total}개</translation>
    </message>
</context>
<context>
    <name>RenamePanel</name>
    <message>
        <location filename="../widgets/rename_panel.py" line="122"/>
        <source>Rename</source>
        <translation>이름 변경</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="125"/>
        <source>Trim characters from beginning and end of ALL filenames below. Add text to the start (Prepend) or end (Append) of ALL the filenames.</source>
        <translatorcomment>해요체 descriptive text. Prepend/Append rendered inline as 앞에 추가 / 뒤에 추가. Flag for native review (spacing + clarity).</translatorcomment>
        <translation>아래 모든 파일명의 앞뒤에서 문자를 잘라내요. 모든 파일명의 앞(앞에 추가) 또는 뒤(뒤에 추가)에 텍스트를 추가해요.</translation>
    </message>
    <message>
        <source>Operations</source>
        <translation type="vanished">작업</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="143"/>
        <source>Trim Start:</source>
        <translation>앞 잘라내기:</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="147"/>
        <location filename="../widgets/rename_panel.py" line="159"/>
        <source> chars</source>
        <translatorcomment>Suffix after a number (e.g. &quot;5자&quot;). Korean uses the counter 자 for characters with no preceding space, so the English leading space is intentionally dropped. Flag for native review (spacing).</translatorcomment>
        <translation>자</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="148"/>
        <source>Remove characters from the beginning of the filename</source>
        <translation>파일명 앞부분의 문자를 제거해요</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="155"/>
        <source>Trim End:</source>
        <translation>뒤 잘라내기:</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="160"/>
        <source>Remove characters from the end of the filename (before extension)</source>
        <translation>파일명 뒷부분(확장자 앞)의 문자를 제거해요</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="165"/>
        <source>Clear</source>
        <translation>지우기</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="181"/>
        <source>Remove Underscores</source>
        <translatorcomment>underscore → 밑줄. Flag for native review.</translatorcomment>
        <translation>밑줄 제거</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="186"/>
        <source>Space Dashes</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="189"/>
        <source>Add spaces around a dash that has none (Artist-Track → Artist - Track). Dashes that already have spaces are left as-is. Helps searching by artist or track name in DJ software.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="218"/>
        <source>Prepend Text</source>
        <translation>앞에 추가</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="221"/>
        <source>Append Text</source>
        <translation>뒤에 추가</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="247"/>
        <location filename="../widgets/rename_panel.py" line="255"/>
        <source>Preview</source>
        <translatorcomment>Preview → 미리 보기 (Apple Korean Finder exact term).</translatorcomment>
        <translation>미리 보기</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="250"/>
        <source>Drop audio files here to add them</source>
        <translation>오디오 파일을 여기에 끌어다 놓으면 추가돼요</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="255"/>
        <source>Original</source>
        <translation>원본</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="255"/>
        <source>Status</source>
        <translation>상태</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="301"/>
        <source>No files to rename</source>
        <translation>이름 변경할 파일이 없어요</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="307"/>
        <source>Undo Last</source>
        <translation>마지막 작업 실행 취소</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="312"/>
        <source>Remove All</source>
        <translation>전체 제거</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="317"/>
        <source>Apply Rename</source>
        <translation>이름 변경 적용</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="324"/>
        <source>Send To</source>
        <translation>보내기</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="327"/>
        <source>Convert</source>
        <translation>변환</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="328"/>
        <source>Analyze</source>
        <translation>분석</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="389"/>
        <source>Text to add at end of filename</source>
        <translation>파일명 끝에 추가할 텍스트</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="391"/>
        <source>Text to add at start of filename</source>
        <translation>파일명 앞에 추가할 텍스트</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="432"/>
        <source>No files</source>
        <translation>파일 없음</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="476"/>
        <source>Conflict</source>
        <translation>충돌</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="493"/>
        <source>{0} files</source>
        <translation>파일 {0}개</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="495"/>
        <source>{0} to rename</source>
        <translation>이름 변경 대상 {0}개</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="497"/>
        <source>{0} conflicts</source>
        <translation>충돌 {0}개</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="635"/>
        <source>Changed</source>
        <translation>변경됨</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="710"/>
        <source>Copy text</source>
        <translation>텍스트 복사</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="710"/>
        <source>Copy {0} names</source>
        <translation>이름 {0}개 복사</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="716"/>
        <source>Remove from list</source>
        <translation>목록에서 제거</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="716"/>
        <source>Remove {0} from list</source>
        <translatorcomment>{0} (a filename) placed before 제거 with a space to avoid attaching a particle to a variable. Flag for native review.</translatorcomment>
        <translation>목록에서 {0} 제거</translation>
    </message>
</context>
<context>
    <name>ReorderableTableWidget</name>
    <message>
        <location filename="../widgets/player_panel.py" line="361"/>
        <source>Drop audio files here</source>
        <translation>오디오 파일을 여기에 끌어다 놓으세요</translation>
    </message>
</context>
<context>
    <name>SettingsPanel</name>
    <message>
        <location filename="../widgets/settings_panel.py" line="60"/>
        <source>Language</source>
        <translation>언어</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="78"/>
        <source>Restart to apply language changes.</source>
        <translation>언어 변경을 적용하려면 재시작하세요.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="86"/>
        <source>Theme</source>
        <translation>테마</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="101"/>
        <source>Night Dark</source>
        <translation>나이트 다크</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="103"/>
        <source>Daylight</source>
        <translation>데이라이트</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="114"/>
        <source>Restart to apply theme changes.</source>
        <translation>테마 변경을 적용하려면 재시작하세요.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="122"/>
        <source>Waveform</source>
        <translatorcomment>Descriptive Settings label — localized normally; the player&apos;s &apos;Waveform Loop Slicer&apos; tool name stays English.</translatorcomment>
        <translation>파형</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="130"/>
        <source>Color of the full-length waveform in the player.</source>
        <translation>플레이어의 전체 파형 색상.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="149"/>
        <source>Default</source>
        <translation>기본값</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="151"/>
        <source>Use the theme&apos;s default waveform color</source>
        <translation>테마의 기본 파형 색상 사용</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="159"/>
        <source>Custom…</source>
        <translation>사용자 설정…</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="170"/>
        <source>Visualizations</source>
        <translation>시각 효과</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="178"/>
        <source>Enable audio visualizations</source>
        <translation>오디오 시각 효과 켜기</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="185"/>
        <source>Adds a visuals selector to the Player and an animated waveform while analyzing or converting.</source>
        <translation>플레이어에 시각 효과 선택 메뉴를 추가하고, 분석 또는 변환 중에 움직이는 파형을 표시합니다.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="196"/>
        <source>Tempo Range</source>
        <translatorcomment>tempo → 템포 (loanword). Flag for native review.</translatorcomment>
        <translation>템포 범위</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="204"/>
        <source>Min 50, Max 250.</source>
        <translation>최소 50, 최대 250.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="210"/>
        <source>Lowest BPM</source>
        <translation>최저 BPM</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="224"/>
        <source>Highest BPM</source>
        <translation>최고 BPM</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="239"/>
        <source>Key/BPM adding to filename after analysis</source>
        <translatorcomment>key → 조성. Flag for native review.</translatorcomment>
        <translation>분석 후 파일명에 조성/BPM 추가</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="247"/>
        <source>Auto-analyze when dropping or sending to the Analyze panel</source>
        <translation>분석 패널에 끌어다 놓거나 보낼 때 자동 분석</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="252"/>
        <source>Automatically write BPM to metadata after analysis</source>
        <translatorcomment>Particle: BPM (비피엠, ends in ㅁ) takes 을 → &quot;BPM을&quot;. Flag for native review.</translatorcomment>
        <translation>분석 후 BPM을 태그에 자동 기록</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="256"/>
        <source>BPM rounds to the nearest whole number when written to metadata.</source>
        <translation>BPM은 메타데이터에 기록될 때 가장 가까운 정수로 반올림됩니다.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="261"/>
        <source>Automatically write the key to metadata after analysis</source>
        <translatorcomment>key → 조성; 조성을 (object particle 을 after consonant). Flag for native review.</translatorcomment>
        <translation>분석 후 조성을 태그에 자동 기록</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="265"/>
        <source>Automatically rename files after analysis</source>
        <translation>분석 후 파일 이름 자동 변경</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="272"/>
        <source>Write key to comment</source>
        <translatorcomment>key → 조성; comment → 코멘트 (consistent with the Comment tag). Flag for native review.</translatorcomment>
        <translation>조성을 코멘트에 기록</translation>
    </message>
    <message>
        <source>Secondary to energy</source>
        <translatorcomment>Means the key is placed AFTER energy in the comment (energy first, key second). Rendered &quot;에너지 다음에 표시&quot;. Flag for native review.</translatorcomment>
        <translation type="vanished">에너지 다음에 표시</translation>
    </message>
    <message>
        <source>When both this and the Energy Tag comment are written, put energy first and key second.</source>
        <translatorcomment>key → 조성. 해요체. Flag for native review.</translatorcomment>
        <translation type="vanished">이 항목과 에너지 태그 코멘트를 모두 기록할 때, 에너지를 먼저, 조성을 나중에 표시해요.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="278"/>
        <source>Naming format:</source>
        <translation>이름 형식:</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="287"/>
        <source>128 8A - Original_File_Name</source>
        <translatorcomment>Example pattern; the &quot;Original_File_Name&quot; placeholder is translated to 원본_파일명 so Korean users see where the original name lands. BPM/key code kept Latin. Flag for native review.</translatorcomment>
        <translation>128 8A - 원본_파일명</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="287"/>
        <source>BPM + Key prefix</source>
        <translatorcomment>key → 조성; prefix → 접두사.</translatorcomment>
        <translation>BPM + 조성 접두사</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="288"/>
        <source>8A 128 - Original_File_Name</source>
        <translation>8A 128 - 원본_파일명</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="288"/>
        <source>Key + BPM prefix</source>
        <translation>조성 + BPM 접두사</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="289"/>
        <source>8A - Original_File_Name</source>
        <translation>8A - 원본_파일명</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="289"/>
        <source>Key prefix only</source>
        <translation>조성 접두사만</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="290"/>
        <source>Original_File_Name - 8A 128</source>
        <translation>원본_파일명 - 8A 128</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="290"/>
        <source>suffix: Key + BPM</source>
        <translatorcomment>suffix → 접미사; key → 조성.</translatorcomment>
        <translation>접미사: 조성 + BPM</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="291"/>
        <source>Original_File_Name - 8A</source>
        <translation>원본_파일명 - 8A</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="291"/>
        <source>suffix: Key only</source>
        <translation>접미사: 조성만</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="314"/>
        <source>Notation</source>
        <translatorcomment>notation → 표기법. Flag for native review.</translatorcomment>
        <translation>표기법</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="324"/>
        <source>Only one notation can be active at a time. Applies to the key written to tags/filenames during analysis and to the Keyboard panel key labels.</source>
        <translatorcomment>key → 조성; &quot;Keyboard panel key labels&quot; → 건반 패널의 건반 레이블 (piano keys). 해요체. Flag for native review.</translatorcomment>
        <translation>한 번에 하나의 표기법만 활성화할 수 있어요. 분석 중 태그/파일명에 기록되는 조성과 건반 패널의 건반 레이블에 적용돼요.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="336"/>
        <source>👑 Key Codes  (8A, 5A, 2B)</source>
        <translation>👑 키 코드  (8A, 5A, 2B)</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="337"/>
        <source>Traditional Key Notation  (Am, Ebm, F#…)</source>
        <translatorcomment>key → 조성; note names (Am, Ebm, F#) kept Latin per CLAUDE.md.</translatorcomment>
        <translation>전통 조성 표기  (Am, Ebm, F#…)</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="338"/>
        <source>Traktor Open Key  (1m, 10m, 9d…)</source>
        <translatorcomment>Traktor Open Key kept as a product name (English); code values kept Latin.</translatorcomment>
        <translation>Traktor Open Key  (1m, 10m, 9d…)</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="354"/>
        <source>Energy Tag</source>
        <translation>에너지 태그</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="362"/>
        <source>Write energy level to Comment tag</source>
        <translatorcomment>energy level → 에너지 레벨; Comment tag → 코멘트 태그.</translatorcomment>
        <translation>에너지 레벨을 코멘트 태그에 기록</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="370"/>
        <source>Energy level written first</source>
        <translation>에너지 레벨을 먼저 기록</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="374"/>
        <source>When both energy and key are written to the comment, put energy first and key second.</source>
        <translation>에너지와 조성을 모두 코멘트에 기록할 때 에너지를 먼저, 조성을 나중에 기록합니다.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="380"/>
        <source>Format:</source>
        <translation>형식:</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="388"/>
        <source>Number only  (7)</source>
        <translation>숫자만  (7)</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="389"/>
        <source>With label  (Energy 7)</source>
        <translatorcomment>&quot;Energy 7&quot; left in English because it is the literal text written to the tag, not UI prose.</translatorcomment>
        <translation>레이블 포함  (Energy 7)</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="398"/>
        <source>Write mode:</source>
        <translation>기록 방식:</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="406"/>
        <source>Prepend to existing comment</source>
        <translation>기존 코멘트 앞에 추가</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="407"/>
        <source>Append to existing comment</source>
        <translation>기존 코멘트 뒤에 추가</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="408"/>
        <source>Replace existing comment</source>
        <translation>기존 코멘트 대체</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="569"/>
        <source>Waveform color</source>
        <translation>파형 색상</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="601"/>
        <location filename="../widgets/settings_panel.py" line="614"/>
        <source>Restart required</source>
        <translation>재시작 필요</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="603"/>
        <source>The language change will take effect the next time you restart Mixed in P.</source>
        <translatorcomment>Product name &quot;Mixed in P&quot; kept Latin; object particle 를 after the vowel-final &quot;P&quot; (피). Flag for native review.</translatorcomment>
        <translation>언어 변경은 Mixed in P를 다음에 재시작할 때 적용돼요.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="616"/>
        <source>The theme change will take effect the next time you restart Mixed in P.</source>
        <translation>테마 변경은 Mixed in P를 다음에 재시작할 때 적용돼요.</translation>
    </message>
</context>
<context>
    <name>Sidebar</name>
    <message>
        <location filename="../widgets/sidebar.py" line="167"/>
        <location filename="../widgets/sidebar.py" line="304"/>
        <source>Collapse sidebar</source>
        <translation>사이드바 접기</translation>
    </message>
    <message>
        <location filename="../widgets/sidebar.py" line="184"/>
        <source>Player</source>
        <translation>플레이어</translation>
    </message>
    <message>
        <location filename="../widgets/sidebar.py" line="185"/>
        <source>Rename</source>
        <translation>이름 변경</translation>
    </message>
    <message>
        <location filename="../widgets/sidebar.py" line="186"/>
        <source>Convert</source>
        <translation>변환</translation>
    </message>
    <message>
        <location filename="../widgets/sidebar.py" line="187"/>
        <source>Analyze</source>
        <translation>분석</translation>
    </message>
    <message>
        <location filename="../widgets/sidebar.py" line="188"/>
        <source>Keyboard</source>
        <translatorcomment>건반 (musical keyboard panel), not 키보드.</translatorcomment>
        <translation>건반</translation>
    </message>
    <message>
        <location filename="../widgets/sidebar.py" line="189"/>
        <source>Metadata</source>
        <translation>메타데이터</translation>
    </message>
    <message>
        <location filename="../widgets/sidebar.py" line="190"/>
        <source>Spectrum</source>
        <translation>스펙트럼</translation>
    </message>
    <message>
        <location filename="../widgets/sidebar.py" line="229"/>
        <location filename="../widgets/sidebar.py" line="237"/>
        <source>Settings</source>
        <translatorcomment>Settings → 설정 (Apple Korean standard).</translatorcomment>
        <translation>설정</translation>
    </message>
    <message>
        <location filename="../widgets/sidebar.py" line="241"/>
        <location filename="../widgets/sidebar.py" line="249"/>
        <source>History</source>
        <translatorcomment>History → 기록 (native, polished) over loanword 히스토리. Flag for native review.</translatorcomment>
        <translation>기록</translation>
    </message>
    <message>
        <location filename="../widgets/sidebar.py" line="304"/>
        <source>Expand sidebar</source>
        <translation>사이드바 펼치기</translation>
    </message>
    <message>
        <location filename="../widgets/sidebar.py" line="337"/>
        <source>Auto</source>
        <translation>자동</translation>
    </message>
</context>
<context>
    <name>SliceSection</name>
    <message>
        <location filename="../widgets/slice_section.py" line="93"/>
        <location filename="../widgets/slice_section.py" line="332"/>
        <source>▸  Waveform Loop Slicer</source>
        <translatorcomment>waveform → 파형, loop → 루프, slicer → 슬라이서 (Hangul per glossary). Triangle disclosure marker preserved.</translatorcomment>
        <translation>▸  파형 루프 슬라이서</translation>
    </message>
    <message>
        <location filename="../widgets/slice_section.py" line="152"/>
        <source>Slice start time (m:ss:mmm) — type to set</source>
        <translation>슬라이스 시작 시간 (m:ss:mmm) — 입력하여 설정</translation>
    </message>
    <message>
        <location filename="../widgets/slice_section.py" line="161"/>
        <source>Slice end time (m:ss:mmm) — type to set</source>
        <translation>슬라이스 종료 시간 (m:ss:mmm) — 입력하여 설정</translation>
    </message>
    <message>
        <location filename="../widgets/slice_section.py" line="163"/>
        <location filename="../widgets/slice_section.py" line="170"/>
        <source>Mark</source>
        <translatorcomment>Mark (a point) → 표시. Flag for native review.</translatorcomment>
        <translation>표시</translation>
    </message>
    <message>
        <location filename="../widgets/slice_section.py" line="164"/>
        <source>Mark start at playhead (Q)</source>
        <translatorcomment>playhead → 재생 위치. Shortcut letter kept Latin. Flag for native review.</translatorcomment>
        <translation>재생 위치를 시작점으로 표시 (Q)</translation>
    </message>
    <message>
        <location filename="../widgets/slice_section.py" line="171"/>
        <source>Mark end at playhead (E)</source>
        <translation>재생 위치를 끝점으로 표시 (E)</translation>
    </message>
    <message>
        <location filename="../widgets/slice_section.py" line="186"/>
        <source>Nudge start marker back 10 ms</source>
        <translation>시작점 마커를 10 ms 뒤로 이동</translation>
    </message>
    <message>
        <location filename="../widgets/slice_section.py" line="188"/>
        <source>Nudge start marker forward 10 ms</source>
        <translation>시작점 마커를 10 ms 앞으로 이동</translation>
    </message>
    <message>
        <location filename="../widgets/slice_section.py" line="190"/>
        <source>Nudge end marker back 10 ms</source>
        <translation>끝점 마커를 10 ms 뒤로 이동</translation>
    </message>
    <message>
        <location filename="../widgets/slice_section.py" line="192"/>
        <source>Nudge end marker forward 10 ms</source>
        <translation>끝점 마커를 10 ms 앞으로 이동</translation>
    </message>
    <message>
        <location filename="../widgets/slice_section.py" line="220"/>
        <source>Length</source>
        <translation>길이</translation>
    </message>
    <message>
        <location filename="../widgets/slice_section.py" line="224"/>
        <source>Shorten slice by 10 ms</source>
        <translation>슬라이스를 10 ms 줄이기</translation>
    </message>
    <message>
        <location filename="../widgets/slice_section.py" line="228"/>
        <source>Slice length (m:ss:mmm) — type to set; moves the end marker</source>
        <translation>슬라이스 길이 (m:ss:mmm) — 입력하여 설정; 끝점 마커를 이동합니다</translation>
    </message>
    <message>
        <location filename="../widgets/slice_section.py" line="230"/>
        <source>Lengthen slice by 10 ms</source>
        <translation>슬라이스를 10 ms 늘이기</translation>
    </message>
    <message>
        <location filename="../widgets/slice_section.py" line="245"/>
        <source>&lt; Start</source>
        <translation>&lt; 시작점</translation>
    </message>
    <message>
        <location filename="../widgets/slice_section.py" line="248"/>
        <source>Jump playhead to start marker (S)</source>
        <translatorcomment>marker → 마커; playhead → 재생 위치.</translatorcomment>
        <translation>재생 위치를 시작 마커로 이동 (S)</translation>
    </message>
    <message>
        <location filename="../widgets/slice_section.py" line="250"/>
        <source>Loop</source>
        <translatorcomment>loop → 루프 (Hangul per glossary).</translatorcomment>
        <translation>루프</translation>
    </message>
    <message>
        <location filename="../widgets/slice_section.py" line="255"/>
        <source>Loop playback between the start and end markers (L)</source>
        <translation>시작과 끝 마커 사이를 루프 재생 (L)</translation>
    </message>
    <message>
        <location filename="../widgets/slice_section.py" line="262"/>
        <source>Save Slice As:</source>
        <translatorcomment>The cut segment (slice noun) → 자른 구간; saving it under a name. Flag for native review.</translatorcomment>
        <translation>자른 구간 저장 이름:</translation>
    </message>
    <message>
        <location filename="../widgets/slice_section.py" line="267"/>
        <source>output filename</source>
        <translation>출력 파일명</translation>
    </message>
    <message>
        <location filename="../widgets/slice_section.py" line="276"/>
        <source>Choose save folder</source>
        <translation>저장 폴더 선택</translation>
    </message>
    <message>
        <location filename="../widgets/slice_section.py" line="283"/>
        <source>Slice</source>
        <translatorcomment>Slice (verb) action button → 자르기 (-기 nominalization) per glossary.</translatorcomment>
        <translation>자르기</translation>
    </message>
    <message>
        <location filename="../widgets/slice_section.py" line="332"/>
        <source>▾  Waveform Loop Slicer</source>
        <translation>▾  파형 루프 슬라이서</translation>
    </message>
    <message>
        <location filename="../widgets/slice_section.py" line="560"/>
        <source>Choose Save Folder</source>
        <translation>저장 폴더 선택</translation>
    </message>
    <message>
        <location filename="../widgets/slice_section.py" line="579"/>
        <source>Saved: {0}</source>
        <translation>저장됨: {0}</translation>
    </message>
    <message>
        <location filename="../widgets/slice_section.py" line="584"/>
        <source>Error: {0}</source>
        <translation>오류: {0}</translation>
    </message>
</context>
<context>
    <name>SpectrogramView</name>
    <message>
        <location filename="../widgets/spectrum_panel.py" line="83"/>
        <source>Drop a single audio file to view its spectrum</source>
        <translation>오디오 파일 하나를 끌어다 놓으면 스펙트럼을 볼 수 있어요</translation>
    </message>
</context>
<context>
    <name>SpectrumPanel</name>
    <message>
        <location filename="../widgets/spectrum_panel.py" line="254"/>
        <source>Spectrum</source>
        <translation>스펙트럼</translation>
    </message>
    <message>
        <location filename="../widgets/spectrum_panel.py" line="259"/>
        <source>Drop a single audio file to see its acoustic spectrum. Frequency runs bottom (0 Hz) to top (Nyquist); time runs left to right; colour shows magnitude. Handy for spotting lossy-encode low-pass cutoffs.</source>
        <translatorcomment>Technical terms: frequency → 주파수, Nyquist → 나이퀴스트, magnitude → 크기, lossy-encode → 손실 인코딩, low-pass → 저역 통과, cutoff → 컷오프. Hz kept Latin. 해요체. Flag for native review.</translatorcomment>
        <translation>오디오 파일 하나를 끌어다 놓으면 음향 스펙트럼을 볼 수 있어요. 주파수는 아래(0 Hz)에서 위(나이퀴스트)로, 시간은 왼쪽에서 오른쪽으로 흐르고, 색상은 크기를 나타내요. 손실 인코딩의 저역 통과 컷오프를 찾을 때 유용해요.</translation>
    </message>
    <message>
        <source>File</source>
        <translation type="vanished">파일</translation>
    </message>
    <message>
        <location filename="../widgets/spectrum_panel.py" line="313"/>
        <source>Sample rate</source>
        <translatorcomment>DSP term → 샘플 레이트 (not the producer &quot;sample&quot;). Consistent with the Conversion panel. Flag for native review.</translatorcomment>
        <translation>샘플 레이트</translation>
    </message>
    <message>
        <location filename="../widgets/spectrum_panel.py" line="314"/>
        <source>Key</source>
        <translatorcomment>Musical key → 조성. Flag for native review.</translatorcomment>
        <translation>조성</translation>
    </message>
    <message>
        <location filename="../widgets/spectrum_panel.py" line="315"/>
        <source>BPM</source>
        <translation>BPM</translation>
    </message>
    <message>
        <location filename="../widgets/spectrum_panel.py" line="335"/>
        <source>Sensitivity:</source>
        <translation>감도:</translation>
    </message>
    <message>
        <location filename="../widgets/spectrum_panel.py" line="346"/>
        <location filename="../widgets/spectrum_panel.py" line="428"/>
        <location filename="../widgets/spectrum_panel.py" line="443"/>
        <source>{0} dB range</source>
        <translation>{0} dB 범위</translation>
    </message>
    <message>
        <location filename="../widgets/spectrum_panel.py" line="402"/>
        <location filename="../widgets/spectrum_panel.py" line="403"/>
        <source>Analyzing…</source>
        <translation>분석 중…</translation>
    </message>
    <message>
        <location filename="../widgets/spectrum_panel.py" line="492"/>
        <source>Could not analyze this file.</source>
        <translation>이 파일을 분석할 수 없어요.</translation>
    </message>
    <message>
        <location filename="../widgets/spectrum_panel.py" line="493"/>
        <source>Error: {0}</source>
        <translation>오류: {0}</translation>
    </message>
</context>
<context>
    <name>VisualizerWindow</name>
    <message>
        <location filename="../widgets/vis_canvas.py" line="370"/>
        <source>Visualizer</source>
        <translation>시각 효과</translation>
    </message>
</context>
</TS>
