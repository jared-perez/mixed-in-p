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
        <location filename="../widgets/analysis_panel.py" line="339"/>
        <location filename="../widgets/analysis_panel.py" line="434"/>
        <source>Analyze</source>
        <translatorcomment>Dual-use as panel title and action button → bare noun 분석 (works for both); &quot;분석하기&quot; would read oddly as a title. Flag for native review.</translatorcomment>
        <translation>분석</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="342"/>
        <source>Drop files to analyze, unless changed in settings. Results update in real-time.</source>
        <translatorcomment>해요체 descriptive sentence. &quot;unless changed in settings&quot; rendered as &quot;설정에서 변경한 경우는 예외예요&quot;. Flag for native review (phrasing + spacing).</translatorcomment>
        <translation>파일을 끌어다 놓으면 분석해요. 설정에서 변경한 경우는 예외예요. 결과는 실시간으로 업데이트돼요.</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="349"/>
        <source>Auto</source>
        <translation>자동</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="355"/>
        <source>Auto-analyze when dropping or sending to the Analyze panel</source>
        <translatorcomment>Checkbox label → noun phrase. &quot;sending&quot; refers to the Send To (보내기) routing. Flag for native review.</translatorcomment>
        <translation>분석 패널에 끌어다 놓거나 보낼 때 자동 분석</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="364"/>
        <source>Freeze</source>
        <translation>동결</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="381"/>
        <source>Drop files here to analyze immediately</source>
        <translation>여기에 끌어다 놓으면 바로 분석해요</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="430"/>
        <source>Clear Results</source>
        <translatorcomment>Action button → -기 nominalization (지우기) per Apple Korean UI convention.</translatorcomment>
        <translation>결과 지우기</translation>
    </message>
    <message>
        <source>Remove Selected</source>
        <translation type="vanished">선택 항목 제거</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="441"/>
        <source>Send To</source>
        <translatorcomment>Localized per CLAUDE.md (not left as a Latin island). 보내기 = Apple Korean nominalized form.</translatorcomment>
        <translation>보내기</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="443"/>
        <source>Convert</source>
        <translation>변환</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="444"/>
        <source>Player</source>
        <translatorcomment>플레이어 (Hangul loanword) per glossary.</translatorcomment>
        <translation>플레이어</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="516"/>
        <source>{n} analyzed</source>
        <translatorcomment>Counter 개 for files. &quot;분석됨&quot; passive. Flag counter choice for native review.</translatorcomment>
        <translation>{n}개 분석됨</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="518"/>
        <source>{n} errors</source>
        <translation>오류 {n}개</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="520"/>
        <source>{n} pending</source>
        <translation>대기 중 {n}개</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="522"/>
        <source>{n} in progress</source>
        <translation>진행 중 {n}개</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="524"/>
        <source>No results yet</source>
        <translation>아직 결과가 없어요</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="568"/>
        <source>Let analysis write tags and rename files again</source>
        <translation>분석이 다시 태그를 기록하고 파일 이름을 변경할 수 있도록 합니다</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="570"/>
        <source>Stop analysis writing tags or renaming files, until you unfreeze</source>
        <translation>해제할 때까지 분석이 태그를 기록하거나 파일 이름을 변경하지 않도록 합니다</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="599"/>
        <source>Open File Location</source>
        <translation>파일 위치 열기</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="601"/>
        <source>Remove</source>
        <translation>제거</translation>
    </message>
</context>
<context>
    <name>AnalysisTableModel</name>
    <message>
        <location filename="../widgets/analysis_panel.py" line="58"/>
        <source>Name</source>
        <translation>이름</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="59"/>
        <source>BPM</source>
        <translation>BPM</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="60"/>
        <location filename="../widgets/analysis_panel.py" line="62"/>
        <source>Conf</source>
        <translatorcomment>&quot;Conf&quot; = confidence → 신뢰도. Column header; longer than the English abbreviation — verify it fits the column width. Flag for native review.</translatorcomment>
        <translation>신뢰도</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="61"/>
        <source>Key</source>
        <translatorcomment>조성 = musical key (music-theory term, not casual 키). Column shows the detected key. Flag for native review.</translatorcomment>
        <translation>조성</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="63"/>
        <source>Key Code</source>
        <translatorcomment>The harmonic key-code label → 키 코드 (Hangul). Distinct from 조성 (the musical key itself).</translatorcomment>
        <translation>키 코드</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="64"/>
        <source>Alt Keys</source>
        <translation>대체 조성</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="65"/>
        <source>Energy</source>
        <translation>에너지</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="66"/>
        <source>Status</source>
        <translation>상태</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="139"/>
        <source>WAV files do not store metadata, but the filename can still be changed.</source>
        <translatorcomment>WAV kept in English per the glossary (audio format code); the rest reuses this language&apos;s existing wording for tags/metadata.</translatorcomment>
        <translation>WAV 파일은 메타데이터를 저장하지 않지만 파일 이름은 변경할 수 있습니다.</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="153"/>
        <source>Queued</source>
        <translatorcomment>Status column in the Analyze table; matches the stem already used for this language&apos;s Convert status column.</translatorcomment>
        <translation>대기열</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="154"/>
        <source>Pending</source>
        <translatorcomment>Status column in the Analyze table; matches the stem already used for this language&apos;s Convert status column.</translatorcomment>
        <translation>대기 중</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="155"/>
        <source>Analyzing</source>
        <translatorcomment>Status column in the Analyze table; matches the stem already used for this language&apos;s Convert status column.</translatorcomment>
        <translation>분석 중</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="156"/>
        <source>Analyzed</source>
        <translatorcomment>Status column in the Analyze table; matches the stem already used for this language&apos;s Convert status column.</translatorcomment>
        <translation>분석됨</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="157"/>
        <source>Error</source>
        <translation>오류</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="174"/>
        <source>WAV file</source>
        <translatorcomment>WAV kept in English per the glossary (audio format code); the rest reuses this language&apos;s existing wording for tags/metadata.</translatorcomment>
        <translation>WAV 파일</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="176"/>
        <source>Analyzed, no tags</source>
        <translatorcomment>WAV kept in English per the glossary (audio format code); the rest reuses this language&apos;s existing wording for tags/metadata.</translatorcomment>
        <translation>분석됨, 태그 없음</translation>
    </message>
    <message>
        <location filename="../widgets/analysis_panel.py" line="202"/>
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
        <location filename="../widgets/conversion_panel.py" line="115"/>
        <location filename="../widgets/conversion_panel.py" line="232"/>
        <source>Convert</source>
        <translatorcomment>Dual-use title/button → bare noun 변환.</translatorcomment>
        <translation>변환</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="118"/>
        <source>Convert audio files between formats (WAV, FLAC, AIFF, MP3).</source>
        <translation>오디오 파일을 다른 형식으로 변환해요 (WAV, FLAC, AIFF, MP3).</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="124"/>
        <source>Target Format:</source>
        <translation>대상 형식:</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="132"/>
        <source>Sample Rate:</source>
        <translatorcomment>DSP term &quot;sample rate&quot; (not the producer &quot;sample&quot;) → 샘플 레이트, the standard loanword in Korean audio software. Flag for native review.</translatorcomment>
        <translation>샘플 레이트:</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="138"/>
        <location filename="../widgets/conversion_panel.py" line="155"/>
        <source>Keep source</source>
        <translatorcomment>Combo item: keep the source file&apos;s own sample rate / bit depth (the engine leaves that axis alone).</translatorcomment>
        <translation>원본 유지</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="139"/>
        <source>96 kHz (DVD)</source>
        <translation>96 kHz (DVD)</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="140"/>
        <source>48 kHz (DAT)</source>
        <translation>48 kHz (DAT)</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="141"/>
        <source>44.1 kHz (CD)</source>
        <translation>44.1 kHz (CD)</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="142"/>
        <source>32 kHz</source>
        <translation>32 kHz</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="152"/>
        <source>Bit Depth:</source>
        <translatorcomment>bit depth → 비트 심도 (standard Korean DSP term).</translatorcomment>
        <translation>비트 심도:</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="156"/>
        <source>32 bit</source>
        <translation>32비트</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="157"/>
        <source>24 bit (DVD)</source>
        <translation>24비트 (DVD)</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="158"/>
        <source>16 bit (CD)</source>
        <translation>16비트 (CD)</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="159"/>
        <source>8 bit</source>
        <translation>8비트</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="169"/>
        <source>Bitrate:</source>
        <translation>비트레이트:</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="190"/>
        <source>Files</source>
        <translatorcomment>파일 (Hangul) per glossary — Apple Korean Finder standard, never 문서.</translatorcomment>
        <translation>파일</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="193"/>
        <source>Drop audio files here to add them</source>
        <translation>오디오 파일을 여기에 끌어다 놓으면 추가돼요</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="196"/>
        <source>Filename</source>
        <translation>파일명</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="197"/>
        <source>From</source>
        <translatorcomment>Column = source format → 원본 (rather than literal &quot;~에서&quot;). Pairs with 대상 below. Flag for native review.</translatorcomment>
        <translation>원본</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="198"/>
        <source>To</source>
        <translatorcomment>Column = target format → 대상. Pairs with 원본 above.</translatorcomment>
        <translation>대상</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="199"/>
        <source>Status</source>
        <translation>상태</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="226"/>
        <location filename="../widgets/conversion_panel.py" line="578"/>
        <source>No files</source>
        <translation>파일 없음</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="239"/>
        <source>Send To</source>
        <translation>보내기</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="241"/>
        <source>Select at least one file to send.</source>
        <translation>보낼 파일을 하나 이상 선택하세요.</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="243"/>
        <source>Analyze</source>
        <translation>분석</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="244"/>
        <source>Rename</source>
        <translatorcomment>이름 변경 = Apple Korean Finder term for Rename.</translatorcomment>
        <translation>이름 변경</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="245"/>
        <source>Player</source>
        <translation>플레이어</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="254"/>
        <source>Lossy files not allowed</source>
        <translatorcomment>lossy → 손실 (audio term). Flag for native review.</translatorcomment>
        <translation>손실 파일은 허용되지 않아요</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="457"/>
        <source>Open File Location</source>
        <translation>파일 위치 열기</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="459"/>
        <source>Remove</source>
        <translation>제거</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="534"/>
        <location filename="../widgets/conversion_panel.py" line="735"/>
        <source>Done</source>
        <translation>완료</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="547"/>
        <source>Same format</source>
        <translation>동일한 형식</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="550"/>
        <source>Choose a lower sample rate or bit depth to convert this file.</source>
        <translation>이 파일을 변환하려면 더 낮은 샘플 레이트 또는 비트 심도를 선택하세요.</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="553"/>
        <source>Would upsample</source>
        <translatorcomment>Status label in a fixed 120px column. Rendered as &apos;higher than the source&apos; rather than the technical noun for upsampling, which does not fit and does not convey that the row is refused.</translatorcomment>
        <translation>원본보다 높음</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="556"/>
        <source>Choose a sample rate and bit depth no higher than this file&apos;s.</source>
        <translation>이 파일보다 높지 않은 샘플 레이트와 비트 심도를 선택하세요.</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="559"/>
        <location filename="../widgets/conversion_panel.py" line="727"/>
        <location filename="../widgets/conversion_panel.py" line="757"/>
        <source>Ready</source>
        <translation>준비됨</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="573"/>
        <source>{count} files</source>
        <translation>파일 {count}개</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="575"/>
        <source>{count} to convert</source>
        <translation>변환 대상 {count}개</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="577"/>
        <source>({count} lossy skipped)</source>
        <translation>(손실 {count}개 건너뜀)</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="699"/>
        <source>Converting</source>
        <translation>변환 중</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="720"/>
        <source>Incomplete</source>
        <translation>미완료</translation>
    </message>
    <message>
        <location filename="../widgets/conversion_panel.py" line="720"/>
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
    <name>DuplicatePrompt</name>
    <message>
        <location filename="../widgets/dialogs/duplicate_policy.py" line="187"/>
        <source>Duplicate Tracks</source>
        <extracomment>Horizontal room a button needs beyond its text: the stylesheet&apos;s ``padding: 8px 16px`` on QPushButton, its 1px border, and a little slack. ``QDialogButtonBox QPushButton`` in the stylesheet, so a short label still gets a button of the same size as everywhere else in the app.</extracomment>
        <translation>중복된 곡</translation>
    </message>
    <message numerus="yes">
        <location filename="../widgets/dialogs/duplicate_policy.py" line="191"/>
        <source>%n track(s) are already in &quot;{0}&quot;.</source>
        <translation>
            <numerusform>%n곡이 이미 ‘{0}’에 있습니다.</numerusform>
        </translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/duplicate_policy.py" line="196"/>
        <source>Add them again, or skip them and add only the rest?</source>
        <translation>다시 추가할까요, 아니면 건너뛰고 나머지만 추가할까요?</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/duplicate_policy.py" line="198"/>
        <source>Add them again, or skip them?</source>
        <translation>다시 추가할까요, 아니면 건너뛸까요?</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/duplicate_policy.py" line="201"/>
        <source>Add Duplicates</source>
        <translation>중복 추가</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/duplicate_policy.py" line="204"/>
        <source>Skip Duplicates</source>
        <translation>중복 건너뛰기</translation>
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
        <location filename="../widgets/history_panel.py" line="178"/>
        <location filename="../widgets/history_panel.py" line="404"/>
        <source>Rename History</source>
        <translatorcomment>History → 기록 (more native/polished than the loanword 히스토리), per glossary. Flag for native review.</translatorcomment>
        <translation>이름 변경 기록</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="182"/>
        <location filename="../widgets/history_panel.py" line="406"/>
        <source>View recent rename operations. Select a session to undo it.</source>
        <translatorcomment>Undo → 실행 취소 (Apple/MS/Samsung Korean standard). 해요체.</translatorcomment>
        <translation>최근 이름 변경 작업을 확인해요. 실행을 취소하려면 세션을 선택하세요.</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="196"/>
        <source>Session ID</source>
        <translation>세션 ID</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="196"/>
        <location filename="../widgets/history_panel.py" line="234"/>
        <source>Date/Time</source>
        <translation>날짜/시간</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="196"/>
        <source>Files</source>
        <translation>파일</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="196"/>
        <source>Description</source>
        <translation>설명</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="226"/>
        <source>Name</source>
        <translation>이름</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="227"/>
        <source>BPM</source>
        <translation>BPM</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="228"/>
        <location filename="../widgets/history_panel.py" line="230"/>
        <source>Conf</source>
        <translation>신뢰도</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="229"/>
        <source>Key</source>
        <translation>조성</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="231"/>
        <source>Key Code</source>
        <translation>키 코드</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="232"/>
        <source>Alt Keys</source>
        <translation>대체 조성</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="233"/>
        <source>Energy</source>
        <translation>에너지</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="282"/>
        <location filename="../widgets/history_panel.py" line="591"/>
        <source>{0} Rename Sessions</source>
        <translation>이름 변경 세션 {0}개</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="290"/>
        <location filename="../widgets/history_panel.py" line="535"/>
        <source>{0} Song Keys</source>
        <translation>곡 조성 {0}개</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="309"/>
        <source>Show</source>
        <translation>표시</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="331"/>
        <location filename="../widgets/history_panel.py" line="752"/>
        <location filename="../widgets/history_panel.py" line="765"/>
        <source>Export CSV</source>
        <translation>CSV 내보내기</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="333"/>
        <source>Export the table below to a spreadsheet-friendly CSV file.</source>
        <translation>아래 표를 스프레드시트에서 열 수 있는 CSV 파일로 내보냅니다.</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="449"/>
        <source>Low confidence — this key is worth double-checking.</source>
        <translation>신뢰도가 낮습니다. 이 키는 다시 확인하는 것이 좋습니다.</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="452"/>
        <source>Low confidence — the tempo may be half or double time.</source>
        <translation>신뢰도가 낮습니다. 템포가 절반 또는 두 배일 수 있습니다.</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="649"/>
        <location filename="../widgets/history_panel.py" line="664"/>
        <source>Open File Location</source>
        <translation>파일 위치 열기</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="666"/>
        <source>This file can&apos;t be found — it may have been moved, renamed, or deleted.</source>
        <translation>파일을 찾을 수 없습니다. 이동, 이름 변경 또는 삭제되었을 수 있습니다.</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="753"/>
        <source>There is nothing to export yet.</source>
        <translation>아직 내보낼 항목이 없습니다.</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="775"/>
        <source>Export failed</source>
        <translation>내보내기 실패</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="776"/>
        <source>Could not write the file:
{0}</source>
        <translation>파일을 쓸 수 없습니다:
{0}</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="782"/>
        <source>Export complete</source>
        <translation>내보내기 완료</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="783"/>
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
        <location filename="../widgets/history_panel.py" line="342"/>
        <source>Delete</source>
        <translation>삭제</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="348"/>
        <source>Undo Selected</source>
        <translation>선택 항목 실행 취소</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="399"/>
        <source>Key History</source>
        <translation>조성 기록</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="401"/>
        <source>Recently analyzed tracks and their detected keys.</source>
        <translation>최근 분석한 트랙과 감지된 조성입니다.</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="581"/>
        <source>Renamed {0} files: {1}</source>
        <translation>파일 {0}개 이름 변경 완료: {1}</translation>
    </message>
    <message>
        <source>Renamed {0} files</source>
        <translation type="vanished">파일 {0}개 이름 변경 완료</translation>
    </message>
    <message>
        <location filename="../widgets/history_panel.py" line="585"/>
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
        <location filename="../widgets/keyboard_panel.py" line="583"/>
        <source>Keyboard</source>
        <translatorcomment>The piano panel → 건반 (musical keyboard), NOT 키보드 (computer keyboard), per glossary.</translatorcomment>
        <translation>건반</translation>
    </message>
    <message>
        <location filename="../widgets/keyboard_panel.py" line="586"/>
        <source>Play chords to compare musical keys. Click keys or use QWERTY shortcuts (A-J, K-L-;). Z/X to shift octave.</source>
        <translatorcomment>chords → 코드, musical keys → 조성, &quot;keys&quot; (the things you click) → 건반, octave → 옥타브. QWERTY/letter shortcuts kept Latin. 해요체. Flag for native review.</translatorcomment>
        <translation>코드를 연주해 조성을 비교해요. 건반을 클릭하거나 QWERTY 단축키(A–J, K–L–;)를 사용하세요. Z/X로 옥타브를 이동해요.</translation>
    </message>
    <message>
        <location filename="../widgets/keyboard_panel.py" line="596"/>
        <source>Notation can be changed in settings</source>
        <translation>표기법은 설정에서 변경할 수 있습니다</translation>
    </message>
    <message>
        <location filename="../widgets/keyboard_panel.py" line="610"/>
        <source>Minor Chord</source>
        <translatorcomment>Chord button → 마이너 코드 (producer-context loanword, widely used). Note: distinct from the mode label 단조. Flag for native review.</translatorcomment>
        <translation>마이너 코드</translation>
    </message>
    <message>
        <location filename="../widgets/keyboard_panel.py" line="611"/>
        <source>Major Chord</source>
        <translatorcomment>Chord button → 메이저 코드 (producer-context loanword). Flag for native review.</translatorcomment>
        <translation>메이저 코드</translation>
    </message>
    <message>
        <location filename="../widgets/keyboard_panel.py" line="678"/>
        <source>View</source>
        <translation>보기</translation>
    </message>
    <message>
        <location filename="../widgets/keyboard_panel.py" line="683"/>
        <source>Circle of Fifths</source>
        <translation>5도권</translation>
    </message>
    <message>
        <location filename="../widgets/keyboard_panel.py" line="682"/>
        <source>Hex Grid</source>
        <translation>육각 그리드</translation>
    </message>
    <message>
        <location filename="../widgets/keyboard_panel.py" line="846"/>
        <location filename="../widgets/keyboard_panel.py" line="849"/>
        <source>👑 Key Codes</source>
        <translation>👑 키 코드</translation>
    </message>
    <message>
        <location filename="../widgets/keyboard_panel.py" line="847"/>
        <source>Traditional Key Notation</source>
        <translatorcomment>&quot;Traditional key notation&quot; → 전통 조성 표기 (key → 조성, notation → 표기). Flag for native review.</translatorcomment>
        <translation>전통 조성 표기</translation>
    </message>
    <message>
        <location filename="../widgets/keyboard_panel.py" line="848"/>
        <source>Traktor Open Key</source>
        <translatorcomment>Proper name of Traktor&apos;s notation system — kept in English (product term). Flag for native review.</translatorcomment>
        <translation>Traktor Open Key</translation>
    </message>
</context>
<context>
    <name>MainWindow</name>
    <message>
        <location filename="../main_window.py" line="120"/>
        <source>Mixed in P</source>
        <translation>Mixed in P</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="453"/>
        <location filename="../main_window.py" line="482"/>
        <source>Export All Playlists</source>
        <translation>모든 재생목록 내보내기</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="474"/>
        <source>Export failed</source>
        <translation>내보내기 실패</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="475"/>
        <source>Could not write the file:
{0}</source>
        <translation>파일을 쓸 수 없습니다:
{0}</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="483"/>
        <source>There are no playlists to export yet.</source>
        <translation>아직 내보낼 재생목록이 없습니다.</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="488"/>
        <source>Export complete</source>
        <translation>내보내기 완료</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="489"/>
        <source>Exported {0} playlists ({1} tracks) to:
{2}</source>
        <translation>재생목록 {0}개({1}곡)를 다음 위치로 내보냈습니다:
{2}</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="580"/>
        <source>Select Audio Files</source>
        <translation>오디오 파일 선택</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="591"/>
        <source>Select Folder</source>
        <translation>폴더 선택</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="821"/>
        <source>No Audio Files</source>
        <translation>오디오 파일 없음</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="822"/>
        <source>No audio files found in:
{0}</source>
        <translation>다음 위치에서 오디오 파일을 찾을 수 없어요:
{0}</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="827"/>
        <source>Invalid Folder</source>
        <translation>잘못된 폴더</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="828"/>
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
        <location filename="../main_window.py" line="969"/>
        <source>Analyzing...</source>
        <translation>분석 중...</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="1001"/>
        <source>Complete: {0} analyzed, {1} errors</source>
        <translation>완료: {0}개 분석, 오류 {1}개</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="1005"/>
        <source>Complete: {0} files analyzed</source>
        <translation>완료: 파일 {0}개 분석</translation>
    </message>
    <message>
        <source>Cancelled</source>
        <translation type="vanished">취소됨</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="1180"/>
        <source>Conversion in Progress</source>
        <translation>변환 진행 중</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="1181"/>
        <source>A conversion is already running. Please wait.</source>
        <translation>이미 변환이 실행 중이에요. 잠시 기다리세요.</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="1231"/>
        <source>Converting...</source>
        <translation>변환 중...</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="1247"/>
        <source>Complete: {0} converted, {1} errors</source>
        <translation>완료: {0}개 변환, 오류 {1}개</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="1251"/>
        <source>Complete: {0} files converted</source>
        <translation>완료: 파일 {0}개 변환</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="1470"/>
        <source>Rename in Progress</source>
        <translation>이름 변경 진행 중</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="1471"/>
        <source>A rename operation is already running.</source>
        <translation>이미 이름 변경 작업이 실행 중이에요.</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="1529"/>
        <source>Rename Failed</source>
        <translation>이름 변경 실패</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="1563"/>
        <source>Undo Rename</source>
        <translation>이름 변경 취소</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="1594"/>
        <source>Undo Failed</source>
        <translation>실행 취소 실패</translation>
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
        <location filename="../main_window.py" line="1535"/>
        <source>No Session</source>
        <translation>세션 없음</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="1535"/>
        <source>No rename session to undo.</source>
        <translation>실행 취소할 이름 변경 세션이 없어요.</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="1544"/>
        <source>Confirm Undo</source>
        <translation>실행 취소 확인</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="1545"/>
        <source>Undo renaming of {0} files?</source>
        <translatorcomment>Object particle avoided via 의 + 을 on 이름 변경. Counter 개. Flag for native review.</translatorcomment>
        <translation>파일 {0}개의 이름 변경을 실행 취소할까요?</translation>
    </message>
    <message>
        <source>Undoing rename...</source>
        <translation type="vanished">이름 변경 실행 취소 중...</translation>
    </message>
    <message>
        <location filename="../main_window.py" line="1564"/>
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
        <location filename="../widgets/metadata_panel.py" line="53"/>
        <source>Title</source>
        <translation>제목</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="54"/>
        <source>Artist</source>
        <translation>아티스트</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="55"/>
        <source>Album</source>
        <translation>앨범</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="56"/>
        <source>Label</source>
        <translation>레이블</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="57"/>
        <source>Genre</source>
        <translation>장르</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="58"/>
        <source>BPM</source>
        <translation>BPM</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="59"/>
        <source>Key</source>
        <translatorcomment>Metadata tag for the musical key → 조성. Flag for native review.</translatorcomment>
        <translation>조성</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="60"/>
        <source>Year</source>
        <translation>연도</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="61"/>
        <source>Track #</source>
        <translatorcomment>Track → 트랙 (music-production context). &quot;Track #&quot; → 트랙 번호.</translatorcomment>
        <translation>트랙 번호</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="62"/>
        <source>Comment</source>
        <translatorcomment>ID3 comment tag → 코멘트 (loanword DJs recognize); used consistently with the Settings &quot;Comment tag&quot; strings. Flag for native review (vs 설명).</translatorcomment>
        <translation>코멘트</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="121"/>
        <source>Metadata Editor</source>
        <translation>메타데이터 편집기</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="124"/>
        <source>Drop a single audio file to view and edit its metadata tags.</source>
        <translation>오디오 파일 하나를 끌어다 놓으면 메타데이터 태그를 보고 편집할 수 있어요.</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="169"/>
        <location filename="../widgets/metadata_panel.py" line="519"/>
        <source>Open File Location</source>
        <translation>파일 위치 열기</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="172"/>
        <source>Show this file in Finder / File Explorer.</source>
        <translation>Finder / 파일 탐색기에서 이 파일을 표시합니다.</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="231"/>
        <location filename="../widgets/metadata_panel.py" line="356"/>
        <source>Add field...</source>
        <translation>필드 추가...</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="236"/>
        <source>Add Artwork…</source>
        <translation>아트워크 추가…</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="241"/>
        <source>Remove</source>
        <translation>제거</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="260"/>
        <source>Reload</source>
        <translation>다시 불러오기</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="265"/>
        <source>Eject</source>
        <translatorcomment>Eject → 꺼내기 (Apple Korean). Flag for native review.</translatorcomment>
        <translation>꺼내기</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="324"/>
        <source>Error: {0}</source>
        <translation>오류: {0}</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="521"/>
        <source>This file can&apos;t be found — it may have been moved, renamed, or deleted.</source>
        <translation>파일을 찾을 수 없습니다. 이동, 이름 변경 또는 삭제되었을 수 있습니다.</translation>
    </message>
    <message>
        <location filename="../widgets/metadata_panel.py" line="560"/>
        <source>Select cover art</source>
        <translation>커버 아트 선택</translation>
    </message>
</context>
<context>
    <name>PlayerPanel</name>
    <message>
        <location filename="../widgets/player_panel.py" line="1324"/>
        <source>Player</source>
        <translation>플레이어</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1354"/>
        <location filename="../widgets/player_panel.py" line="2320"/>
        <source>Search all playlists…</source>
        <translation>모든 재생목록 검색…</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1373"/>
        <source>This playlist</source>
        <translation>이 재생목록</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1374"/>
        <source>All playlists</source>
        <translation>모든 재생목록</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1399"/>
        <source>Choose a visualization</source>
        <translation>시각 효과 선택</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1407"/>
        <source>Visuals off</source>
        <translation>시각 효과 끔</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1408"/>
        <source>Backdrop waveform</source>
        <translation>배경: 파형</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1409"/>
        <source>Backdrop oscilloscope</source>
        <translation>배경: 오실로스코프</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1410"/>
        <source>Backdrop spectrum</source>
        <translation>배경: 스펙트럼</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1411"/>
        <source>Backdrop fire</source>
        <translation>배경: 불꽃</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1412"/>
        <source>Backdrop fractal</source>
        <translation>배경: 프랙털</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1413"/>
        <source>Popout oscilloscope</source>
        <translation>별도 창: 오실로스코프</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1414"/>
        <source>Popout spectrum bars</source>
        <translation>별도 창: 스펙트럼 막대</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1415"/>
        <source>Popout fire</source>
        <translation>별도 창: 불꽃</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1416"/>
        <source>Popout fractal</source>
        <translation>별도 창: 프랙털</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1436"/>
        <source>Edit Lock</source>
        <translation>편집 잠금</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1440"/>
        <source>Lock metadata editing in the playlist</source>
        <translation>재생목록의 메타데이터 편집 잠금</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1074"/>
        <location filename="../widgets/player_panel.py" line="2433"/>
        <source>#</source>
        <translation>#</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1075"/>
        <source>Filename</source>
        <translation>파일명</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1076"/>
        <source>Artist</source>
        <translation>아티스트</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1077"/>
        <source>Title</source>
        <translation>제목</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1078"/>
        <source>BPM</source>
        <translation>BPM</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1079"/>
        <source>Key</source>
        <translatorcomment>Playlist column for the musical key → 조성. Flag for native review.</translatorcomment>
        <translation>조성</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1080"/>
        <source>Comment</source>
        <translation>코멘트</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1081"/>
        <source>Duration</source>
        <translatorcomment>Duration → 재생 시간 (playback length).</translatorcomment>
        <translation>재생 시간</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1082"/>
        <source>Year</source>
        <translation>연도</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1536"/>
        <location filename="../widgets/player_panel.py" line="2430"/>
        <source>Playlists</source>
        <translation>재생목록</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1614"/>
        <source>Previous</source>
        <translation>이전</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1625"/>
        <source>Play / Pause  (Space)</source>
        <translatorcomment>Playback → 재생; Pause → 일시정지. Key name &quot;Space&quot; kept Latin.</translatorcomment>
        <translation>재생 / 일시정지  (Space)</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1632"/>
        <source>Stop</source>
        <translation>정지</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1639"/>
        <source>Next</source>
        <translation>다음</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1595"/>
        <source>Vol</source>
        <translatorcomment>Volume abbreviation → 볼륨. Flag for native review (vs 음량).</translatorcomment>
        <translation>볼륨</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1083"/>
        <source>Album</source>
        <translation>앨범</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1084"/>
        <source>Genre</source>
        <translation>장르</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1085"/>
        <source>Track #</source>
        <translation>트랙 번호</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1086"/>
        <source>Label</source>
        <translation>레이블</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1087"/>
        <source>Bitrate</source>
        <translation>비트레이트</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1088"/>
        <source>Energy</source>
        <translation>에너지</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1089"/>
        <source>Art</source>
        <translation>아트워크</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1657"/>
        <location filename="../widgets/player_panel.py" line="2277"/>
        <location filename="../widgets/player_panel.py" line="2282"/>
        <source>Save Playlist</source>
        <translation>재생목록 저장</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1662"/>
        <source>Clear Playlist</source>
        <translatorcomment>playlist → 재생목록; action button → -기 (비우기).</translatorcomment>
        <translation>재생목록 비우기</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1680"/>
        <source>Drag this onto a playlist to add the playing track</source>
        <translation>이것을 재생목록으로 끌어다 놓으면 재생 중인 곡이 추가돼요</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="1880"/>
        <location filename="../widgets/player_panel.py" line="2264"/>
        <source>Scratch</source>
        <translation>Scratch</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="2249"/>
        <source>Playing: {0}</source>
        <translation>재생 중: {0}</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="2261"/>
        <source>Search: {0}</source>
        <translation>검색: {0}</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="2278"/>
        <source>The playlist is empty — add some tracks first.</source>
        <translation>재생목록이 비어 있어요. 먼저 곡을 추가하세요.</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="2282"/>
        <source>Playlist name:</source>
        <translation>재생목록 이름:</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="2317"/>
        <source>Search scope: {0}</source>
        <translation>검색 범위: {0}</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="2322"/>
        <source>Search this playlist…</source>
        <translation>이 재생목록 검색…</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="2341"/>
        <source>No matching tracks</source>
        <translation>일치하는 곡이 없음</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="2654"/>
        <source>File not found:
{0}</source>
        <translation>파일을 찾을 수 없습니다:
{0}</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="3025"/>
        <source>{0}+ results</source>
        <translation>{0}+개 결과</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="3028"/>
        <source>{0} result</source>
        <translation>{0}개 결과</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="3030"/>
        <source>{0} results</source>
        <translation>{0}개 결과</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="3034"/>
        <source>{0} track</source>
        <translatorcomment>Counter for tracks/songs → 곡 per glossary. Korean has no plural; {0} track and {0} tracks render identically. Flag for native review.</translatorcomment>
        <translation>{0}곡</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="3036"/>
        <source>{0} tracks</source>
        <translatorcomment>Counter 곡. Same form as the singular (no Korean plural). Flag for native review.</translatorcomment>
        <translation>{0}곡</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="3972"/>
        <source>“{0}” has moved.</source>
        <translation>‘{0}’이(가) 이동되었습니다.</translation>
    </message>
    <message numerus="yes">
        <location filename="../widgets/player_panel.py" line="3974"/>
        <source>%n of the selected files have moved.</source>
        <translation>
            <numerusform>선택한 파일 중 %n개가 이동되었습니다.</numerusform>
        </translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="3977"/>
        <source>File Has Moved</source>
        <translation>파일이 이동됨</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="3981"/>
        <source>It is no longer at its saved location, so it can&apos;t be added to a playlist or dragged out. A track already playing keeps playing — it was loaded into memory before the file moved.</source>
        <translation>저장된 위치에 더 이상 없으므로 재생목록에 추가하거나 밖으로 끌어낼 수 없습니다. 이미 재생 중인 곡은 계속 재생됩니다. 파일이 이동되기 전에 메모리로 불러왔기 때문입니다.</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="3986"/>
        <source>Right-click the track and choose Locate Missing File…</source>
        <translation>곡을 마우스 오른쪽 버튼으로 클릭하고 ‘누락된 파일 찾기…’를 선택하세요</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="4098"/>
        <source>Locate Missing File…</source>
        <translation>누락된 파일 찾기…</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="4100"/>
        <source>Open File Location</source>
        <translation>파일 위치 열기</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="4101"/>
        <source>Open in Metadata Panel</source>
        <translation>메타데이터 패널에서 열기</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="4102"/>
        <source>Reload Metadata from File</source>
        <translation>파일에서 메타데이터 다시 불러오기</translation>
    </message>
    <message>
        <location filename="../widgets/player_panel.py" line="4104"/>
        <source>Remove from Playlist</source>
        <translation>재생목록에서 제거</translation>
    </message>
</context>
<context>
    <name>PlaylistTree</name>
    <message>
        <location filename="../widgets/playlist_tree.py" line="374"/>
        <source>Scratch</source>
        <translation>Scratch</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="615"/>
        <location filename="../widgets/playlist_tree.py" line="692"/>
        <location filename="../widgets/playlist_tree.py" line="712"/>
        <source>New Playlist</source>
        <translation>새로운 재생목록</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="615"/>
        <location filename="../widgets/playlist_tree.py" line="693"/>
        <location filename="../widgets/playlist_tree.py" line="713"/>
        <source>New Folder</source>
        <translation>새로운 폴더</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="657"/>
        <source>Delete folder &quot;{0}&quot; and everything inside it?</source>
        <translation>폴더 ‘{0}’과(와) 그 안의 모든 항목을 삭제할까요?</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="659"/>
        <source>Delete playlist &quot;{0}&quot;?</source>
        <translation>재생목록 ‘{0}’을(를) 삭제할까요?</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="662"/>
        <source>Delete</source>
        <translation>삭제</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="695"/>
        <location filename="../widgets/playlist_tree.py" line="701"/>
        <source>Rename</source>
        <translation>이름 변경</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="696"/>
        <location filename="../widgets/playlist_tree.py" line="702"/>
        <source>Delete…</source>
        <translation>삭제…</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="698"/>
        <source>Export Folder…</source>
        <translation>폴더 내보내기…</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="706"/>
        <source>Export…</source>
        <translation>내보내기…</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="708"/>
        <source>Export and Copy Tracks…</source>
        <translation>내보내고 곡 복사…</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="727"/>
        <location filename="../widgets/playlist_tree.py" line="734"/>
        <source>Export Playlist</source>
        <translation>재생목록 내보내기</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="728"/>
        <location filename="../widgets/playlist_tree.py" line="797"/>
        <source>This playlist is empty — there is nothing to export.</source>
        <translation>이 재생목록은 비어 있어서 내보낼 항목이 없습니다.</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="749"/>
        <location filename="../widgets/playlist_tree.py" line="857"/>
        <source>Exported {0} tracks to:
{1}</source>
        <translation>{0}곡을 다음 위치로 내보냈습니다:
{1}</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="759"/>
        <source>Export Folder</source>
        <translation>폴더 내보내기</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="777"/>
        <source>Exported {0} playlists ({1} tracks) to:
{2}</source>
        <translation>재생목록 {0}개({1}곡)를 다음 위치로 내보냈습니다:
{2}</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="796"/>
        <location filename="../widgets/playlist_tree.py" line="823"/>
        <source>Export and Copy Tracks</source>
        <translation>내보내고 곡 복사</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="803"/>
        <source>Export in Progress</source>
        <translation>내보내기 진행 중</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="804"/>
        <source>An export is already running. Please wait.</source>
        <translation>이미 내보내기가 진행 중입니다. 잠시 기다려 주세요.</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="808"/>
        <source>Choose Where to Create the Folder</source>
        <translation>폴더를 만들 위치 선택</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="821"/>
        <source>Copying tracks…</source>
        <translation>곡 복사 중…</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="821"/>
        <source>Cancel</source>
        <translation>취소</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="848"/>
        <source>Copying {0}</source>
        <translation>{0} 복사 중</translation>
    </message>
    <message numerus="yes">
        <location filename="../widgets/playlist_tree.py" line="864"/>
        <source>%n track(s) could not be found and were skipped.</source>
        <translation>
            <numerusform>%n곡을 찾을 수 없어 건너뛰었습니다.</numerusform>
        </translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="872"/>
        <location filename="../widgets/playlist_tree.py" line="930"/>
        <source>Export failed</source>
        <translation>내보내기 실패</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="873"/>
        <location filename="../widgets/playlist_tree.py" line="931"/>
        <source>Could not write the file:
{0}</source>
        <translation>파일을 쓸 수 없습니다:
{0}</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="904"/>
        <source>Serato — drag the file onto the crate panel</source>
        <translation>Serato — 파일을 crate 패널로 끌어다 놓기</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="905"/>
        <source>Rekordbox — File → Import Playlist</source>
        <translation>Rekordbox — File → Import Playlist</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="906"/>
        <source>Traktor — File → Import</source>
        <translation>Traktor — File → Import</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="919"/>
        <source>Export complete</source>
        <translation>내보내기 완료</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="922"/>
        <source>To import it:</source>
        <translation>가져오는 방법:</translation>
    </message>
</context>
<context>
    <name>PlaylistTreePanel</name>
    <message>
        <location filename="../widgets/playlist_tree.py" line="1291"/>
        <source>+ Playlist</source>
        <translation>+ 재생목록</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="1292"/>
        <source>+ Folder</source>
        <translation>+ 폴더</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="1315"/>
        <source>Playlist name…</source>
        <translation>재생목록 이름…</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="1362"/>
        <source>Close the playlist filter</source>
        <translation>재생목록 필터 닫기</translation>
    </message>
    <message>
        <location filename="../widgets/playlist_tree.py" line="1364"/>
        <source>Filter playlists by name</source>
        <translation>이름으로 재생목록 필터링</translation>
    </message>
</context>
<context>
    <name>ProgressPanel</name>
    <message>
        <location filename="../widgets/progress_bar.py" line="45"/>
        <location filename="../widgets/progress_bar.py" line="143"/>
        <source>Analyzing...</source>
        <translation>분석 중...</translation>
    </message>
    <message>
        <location filename="../widgets/progress_bar.py" line="54"/>
        <source>Cancel</source>
        <translation>취소</translation>
    </message>
    <message>
        <location filename="../widgets/progress_bar.py" line="165"/>
        <source>Complete</source>
        <translation>완료</translation>
    </message>
    <message>
        <location filename="../widgets/progress_bar.py" line="186"/>
        <source>Cancelled</source>
        <translation>취소됨</translation>
    </message>
</context>
<context>
    <name>QueuePanel</name>
    <message>
        <location filename="../widgets/queue_panel.py" line="42"/>
        <source>Queue</source>
        <translatorcomment>Queue → 대기열 (standard Korean computing term).</translatorcomment>
        <translation>대기열</translation>
    </message>
    <message>
        <location filename="../widgets/queue_panel.py" line="45"/>
        <source>Add files here to queue them for analysis. Use the buttons below to send them to analysis.</source>
        <translation>여기에 파일을 추가하면 분석 대기열에 들어가요. 아래 버튼으로 분석에 보낼 수 있어요.</translation>
    </message>
    <message>
        <location filename="../widgets/queue_panel.py" line="50"/>
        <source>Drop audio files here to add to queue</source>
        <translation>오디오 파일을 여기에 끌어다 놓으면 대기열에 추가돼요</translation>
    </message>
    <message>
        <location filename="../widgets/queue_panel.py" line="79"/>
        <source>0 files in queue</source>
        <translation>대기열에 파일 0개</translation>
    </message>
    <message>
        <location filename="../widgets/queue_panel.py" line="85"/>
        <source>Clear Queue</source>
        <translation>대기열 비우기</translation>
    </message>
    <message>
        <location filename="../widgets/queue_panel.py" line="89"/>
        <source>Analyze Selected</source>
        <translation>선택 항목 분석</translation>
    </message>
    <message>
        <location filename="../widgets/queue_panel.py" line="93"/>
        <source>Analyze All</source>
        <translation>전체 분석</translation>
    </message>
    <message>
        <location filename="../widgets/queue_panel.py" line="113"/>
        <source>{total} files in queue</source>
        <translation>대기열에 파일 {total}개</translation>
    </message>
    <message>
        <location filename="../widgets/queue_panel.py" line="116"/>
        <source>{queued} queued / {total} total files</source>
        <translation>대기 {queued}개 / 전체 파일 {total}개</translation>
    </message>
</context>
<context>
    <name>RelocateDialog</name>
    <message>
        <location filename="../widgets/dialogs/relocate_dialog.py" line="76"/>
        <location filename="../widgets/dialogs/relocate_dialog.py" line="188"/>
        <source>File Not Found</source>
        <translation>파일을 찾을 수 없음</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/relocate_dialog.py" line="95"/>
        <source>This file is no longer where the playlist expects it:</source>
        <translation>이 파일은 재생목록이 예상하는 위치에 더 이상 없습니다:</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/relocate_dialog.py" line="125"/>
        <source>Locate…</source>
        <translation>찾기…</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/relocate_dialog.py" line="128"/>
        <source>Find in Folder…</source>
        <translation>폴더에서 찾기…</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/relocate_dialog.py" line="130"/>
        <source>Scan a folder and relink every missing file found in it</source>
        <translation>폴더를 검사하여 그 안에서 찾은 누락된 파일을 모두 다시 연결합니다</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/relocate_dialog.py" line="135"/>
        <source>Close</source>
        <translation>닫기</translation>
    </message>
    <message numerus="yes">
        <location filename="../widgets/dialogs/relocate_dialog.py" line="148"/>
        <source>%n other file(s) in your playlists are also missing.</source>
        <translation>
            <numerusform>재생목록의 다른 파일 %n개도 누락되었습니다.</numerusform>
        </translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/relocate_dialog.py" line="174"/>
        <source>Locate File</source>
        <translation>파일 찾기</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/relocate_dialog.py" line="176"/>
        <source>Audio Files</source>
        <translation>오디오 파일</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/relocate_dialog.py" line="189"/>
        <source>Could not update the playlist:
{0}</source>
        <translation>재생목록을 업데이트할 수 없습니다:
{0}</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/relocate_dialog.py" line="200"/>
        <source>Nothing is missing any more.</source>
        <translation>더 이상 누락된 항목이 없습니다.</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/relocate_dialog.py" line="205"/>
        <source>Choose a Folder to Search</source>
        <translation>검색할 폴더 선택</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/relocate_dialog.py" line="213"/>
        <source>Searching…</source>
        <translation>검색 중…</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/relocate_dialog.py" line="213"/>
        <source>Cancel</source>
        <translation>취소</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/relocate_dialog.py" line="215"/>
        <location filename="../widgets/dialogs/relocate_dialog.py" line="266"/>
        <location filename="../widgets/dialogs/relocate_dialog.py" line="293"/>
        <source>Find in Folder</source>
        <translation>폴더에서 찾기</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/relocate_dialog.py" line="241"/>
        <source>Checking {0}</source>
        <translation>{0} 확인 중</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/relocate_dialog.py" line="257"/>
        <source>No matching files were found in that folder.</source>
        <translation>그 폴더에서 일치하는 파일을 찾지 못했습니다.</translation>
    </message>
    <message>
        <location filename="../widgets/dialogs/relocate_dialog.py" line="267"/>
        <source>Could not search that folder:
{0}</source>
        <translation>그 폴더를 검색할 수 없습니다:
{0}</translation>
    </message>
    <message numerus="yes">
        <location filename="../widgets/dialogs/relocate_dialog.py" line="272"/>
        <source>%n file(s) were relinked.</source>
        <translation>
            <numerusform>파일 %n개를 다시 연결했습니다.</numerusform>
        </translation>
    </message>
    <message numerus="yes">
        <location filename="../widgets/dialogs/relocate_dialog.py" line="280"/>
        <source>%n of them matched by filename rather than by contents — check they are the tracks you expect.</source>
        <translation>
            <numerusform>그중 %n개는 내용이 아니라 파일 이름으로 일치했습니다. 원하는 곡인지 확인하세요.</numerusform>
        </translation>
    </message>
    <message numerus="yes">
        <location filename="../widgets/dialogs/relocate_dialog.py" line="289"/>
        <source>%n file(s) are still missing.</source>
        <translation>
            <numerusform>파일 %n개가 여전히 누락되었습니다.</numerusform>
        </translation>
    </message>
</context>
<context>
    <name>RenamePanel</name>
    <message>
        <location filename="../widgets/rename_panel.py" line="123"/>
        <source>Rename</source>
        <translation>이름 변경</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="126"/>
        <source>Trim characters from beginning and end of ALL filenames below. Add text to the start (Prepend) or end (Append) of ALL the filenames.</source>
        <translatorcomment>해요체 descriptive text. Prepend/Append rendered inline as 앞에 추가 / 뒤에 추가. Flag for native review (spacing + clarity).</translatorcomment>
        <translation>아래 모든 파일명의 앞뒤에서 문자를 잘라내요. 모든 파일명의 앞(앞에 추가) 또는 뒤(뒤에 추가)에 텍스트를 추가해요.</translation>
    </message>
    <message>
        <source>Operations</source>
        <translation type="vanished">작업</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="144"/>
        <source>Trim Start:</source>
        <translation>앞 잘라내기:</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="148"/>
        <location filename="../widgets/rename_panel.py" line="160"/>
        <source> chars</source>
        <translatorcomment>Suffix after a number (e.g. &quot;5자&quot;). Korean uses the counter 자 for characters with no preceding space, so the English leading space is intentionally dropped. Flag for native review (spacing).</translatorcomment>
        <translation>자</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="149"/>
        <source>Remove characters from the beginning of the filename</source>
        <translation>파일명 앞부분의 문자를 제거해요</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="156"/>
        <source>Trim End:</source>
        <translation>뒤 잘라내기:</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="161"/>
        <source>Remove characters from the end of the filename (before extension)</source>
        <translation>파일명 뒷부분(확장자 앞)의 문자를 제거해요</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="166"/>
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
        <location filename="../widgets/rename_panel.py" line="185"/>
        <source>Space Dashes</source>
        <translation>하이픈 앞뒤 공백</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="191"/>
        <source>Put spaces around a dash: Artist-Track → Artist - Track</source>
        <translation>하이픈 앞뒤에 공백을 넣어요: Artist-Track → Artist - Track</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="216"/>
        <source>Prepend Text</source>
        <translation>앞에 추가</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="219"/>
        <source>Append Text</source>
        <translation>뒤에 추가</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="248"/>
        <location filename="../widgets/rename_panel.py" line="256"/>
        <source>Preview</source>
        <translatorcomment>Preview → 미리 보기 (Apple Korean Finder exact term).</translatorcomment>
        <translation>미리 보기</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="251"/>
        <source>Drop audio files here to add them</source>
        <translation>오디오 파일을 여기에 끌어다 놓으면 추가돼요</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="256"/>
        <source>Original</source>
        <translation>원본</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="256"/>
        <source>Status</source>
        <translation>상태</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="302"/>
        <source>No files to rename</source>
        <translation>이름 변경할 파일이 없어요</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="308"/>
        <source>Undo Last</source>
        <translation>마지막 작업 실행 취소</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="313"/>
        <source>Remove All</source>
        <translation>전체 제거</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="318"/>
        <source>Apply Rename</source>
        <translation>이름 변경 적용</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="325"/>
        <source>Send To</source>
        <translation>보내기</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="328"/>
        <source>Convert</source>
        <translation>변환</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="329"/>
        <source>Analyze</source>
        <translation>분석</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="390"/>
        <source>Text to add at end of filename</source>
        <translation>파일명 끝에 추가할 텍스트</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="392"/>
        <source>Text to add at start of filename</source>
        <translation>파일명 앞에 추가할 텍스트</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="433"/>
        <source>No files</source>
        <translation>파일 없음</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="477"/>
        <source>Conflict</source>
        <translation>충돌</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="494"/>
        <source>{0} files</source>
        <translation>파일 {0}개</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="496"/>
        <source>{0} to rename</source>
        <translation>이름 변경 대상 {0}개</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="498"/>
        <source>{0} conflicts</source>
        <translation>충돌 {0}개</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="636"/>
        <source>Changed</source>
        <translation>변경됨</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="711"/>
        <source>Copy text</source>
        <translation>텍스트 복사</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="711"/>
        <source>Copy {0} names</source>
        <translation>이름 {0}개 복사</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="717"/>
        <source>Remove from list</source>
        <translation>목록에서 제거</translation>
    </message>
    <message>
        <location filename="../widgets/rename_panel.py" line="717"/>
        <source>Remove {0} from list</source>
        <translatorcomment>{0} (a filename) placed before 제거 with a space to avoid attaching a particle to a variable. Flag for native review.</translatorcomment>
        <translation>목록에서 {0} 제거</translation>
    </message>
</context>
<context>
    <name>ReorderableTableWidget</name>
    <message>
        <location filename="../widgets/player_panel.py" line="478"/>
        <source>Drop audio files here</source>
        <translation>오디오 파일을 여기에 끌어다 놓으세요</translation>
    </message>
</context>
<context>
    <name>SettingsPanel</name>
    <message>
        <location filename="../widgets/settings_panel.py" line="71"/>
        <source>Language</source>
        <translation>언어</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="89"/>
        <source>Restart to apply language changes.</source>
        <translation>언어 변경을 적용하려면 재시작하세요.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="103"/>
        <location filename="../widgets/settings_panel.py" line="656"/>
        <source>Default Audio Player</source>
        <translation>기본 오디오 플레이어</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="112"/>
        <source>Make Mixed in P your default audio player</source>
        <translation>Mixed in P를 기본 오디오 플레이어로 설정</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="122"/>
        <source>Opens Windows Settings on the Mixed in P entry, where you can hand it your audio file types. Windows only lets you make that choice yourself.</source>
        <translation>Windows 설정에서 Mixed in P 항목을 엽니다. 거기서 오디오 파일 형식을 지정할 수 있습니다. Windows는 이 선택을 사용자 본인만 할 수 있게 합니다.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="128"/>
        <source>Double-clicking an audio file will open it here. Finder&apos;s Get Info panel puts it back.</source>
        <translation>오디오 파일을 두 번 클릭하면 여기서 열립니다. Finder의 ‘정보 가져오기’에서 되돌릴 수 있습니다.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="139"/>
        <source>Theme</source>
        <translation>테마</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="154"/>
        <source>Night Dark</source>
        <translation>나이트 다크</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="156"/>
        <source>Daylight</source>
        <translation>데이라이트</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="167"/>
        <source>Restart to apply theme changes.</source>
        <translation>테마 변경을 적용하려면 재시작하세요.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="175"/>
        <source>Waveform</source>
        <translatorcomment>Descriptive Settings label — localized normally; the player&apos;s &apos;Waveform Loop Slicer&apos; tool name stays English.</translatorcomment>
        <translation>파형</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="183"/>
        <source>Color of the full-length waveform in the player.</source>
        <translation>플레이어의 전체 파형 색상.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="202"/>
        <source>Default</source>
        <translation>기본값</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="204"/>
        <source>Use the theme&apos;s default waveform color</source>
        <translation>테마의 기본 파형 색상 사용</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="212"/>
        <source>Custom…</source>
        <translation>사용자 설정…</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="223"/>
        <source>Playlist Text Size</source>
        <translation>재생목록 텍스트 크기</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="232"/>
        <source>Size of the track rows in the player. Applies straight away.</source>
        <translation>플레이어의 곡 행 크기입니다. 바로 적용됩니다.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="244"/>
        <source>Small</source>
        <translation>작게</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="245"/>
        <source>Medium</source>
        <translation>보통</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="246"/>
        <source>Large</source>
        <translation>크게</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="261"/>
        <source>Visualizations</source>
        <translation>시각 효과</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="269"/>
        <source>Enable audio visualizations</source>
        <translation>오디오 시각 효과 켜기</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="276"/>
        <source>Adds a visuals selector to the Player and an animated waveform while analyzing or converting.</source>
        <translation>플레이어에 시각 효과 선택 메뉴를 추가하고, 분석 또는 변환 중에 움직이는 파형을 표시합니다.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="287"/>
        <source>Tempo Range</source>
        <translatorcomment>tempo → 템포 (loanword). Flag for native review.</translatorcomment>
        <translation>템포 범위</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="295"/>
        <source>Min 50, Max 250.</source>
        <translation>최소 50, 최대 250.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="301"/>
        <source>Lowest BPM</source>
        <translation>최저 BPM</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="315"/>
        <source>Highest BPM</source>
        <translation>최고 BPM</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="330"/>
        <source>Key/BPM adding to filename after analysis</source>
        <translatorcomment>key → 조성. Flag for native review.</translatorcomment>
        <translation>분석 후 파일명에 조성/BPM 추가</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="338"/>
        <source>Auto-analyze when dropping or sending to the Analyze panel</source>
        <translation>분석 패널에 끌어다 놓거나 보낼 때 자동 분석</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="343"/>
        <source>Automatically write BPM to metadata after analysis</source>
        <translatorcomment>Particle: BPM (비피엠, ends in ㅁ) takes 을 → &quot;BPM을&quot;. Flag for native review.</translatorcomment>
        <translation>분석 후 BPM을 태그에 자동 기록</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="347"/>
        <source>BPM rounds to the nearest whole number when written to metadata.</source>
        <translation>BPM은 메타데이터에 기록될 때 가장 가까운 정수로 반올림됩니다.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="352"/>
        <source>Automatically write the key to metadata after analysis</source>
        <translatorcomment>key → 조성; 조성을 (object particle 을 after consonant). Flag for native review.</translatorcomment>
        <translation>분석 후 조성을 태그에 자동 기록</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="356"/>
        <source>Automatically rename files after analysis</source>
        <translation>분석 후 파일 이름 자동 변경</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="363"/>
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
        <location filename="../widgets/settings_panel.py" line="369"/>
        <source>Naming format:</source>
        <translation>이름 형식:</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="378"/>
        <source>128 8A - Original_File_Name</source>
        <translatorcomment>Example pattern; the &quot;Original_File_Name&quot; placeholder is translated to 원본_파일명 so Korean users see where the original name lands. BPM/key code kept Latin. Flag for native review.</translatorcomment>
        <translation>128 8A - 원본_파일명</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="378"/>
        <source>BPM + Key prefix</source>
        <translatorcomment>key → 조성; prefix → 접두사.</translatorcomment>
        <translation>BPM + 조성 접두사</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="379"/>
        <source>8A 128 - Original_File_Name</source>
        <translation>8A 128 - 원본_파일명</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="379"/>
        <source>Key + BPM prefix</source>
        <translation>조성 + BPM 접두사</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="380"/>
        <source>8A - Original_File_Name</source>
        <translation>8A - 원본_파일명</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="380"/>
        <source>Key prefix only</source>
        <translation>조성 접두사만</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="381"/>
        <source>Original_File_Name - 8A 128</source>
        <translation>원본_파일명 - 8A 128</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="381"/>
        <source>suffix: Key + BPM</source>
        <translatorcomment>suffix → 접미사; key → 조성.</translatorcomment>
        <translation>접미사: 조성 + BPM</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="382"/>
        <source>Original_File_Name - 8A</source>
        <translation>원본_파일명 - 8A</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="382"/>
        <source>suffix: Key only</source>
        <translation>접미사: 조성만</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="405"/>
        <source>Notation</source>
        <translatorcomment>notation → 표기법. Flag for native review.</translatorcomment>
        <translation>표기법</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="415"/>
        <source>Only one notation can be active at a time. Applies to the key written to tags/filenames during analysis and to the Keyboard panel key labels.</source>
        <translatorcomment>key → 조성; &quot;Keyboard panel key labels&quot; → 건반 패널의 건반 레이블 (piano keys). 해요체. Flag for native review.</translatorcomment>
        <translation>한 번에 하나의 표기법만 활성화할 수 있어요. 분석 중 태그/파일명에 기록되는 조성과 건반 패널의 건반 레이블에 적용돼요.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="427"/>
        <source>👑 Key Codes  (8A, 5A, 2B)</source>
        <translation>👑 키 코드  (8A, 5A, 2B)</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="428"/>
        <source>Traditional Key Notation  (Am, Ebm, F#…)</source>
        <translatorcomment>key → 조성; note names (Am, Ebm, F#) kept Latin per CLAUDE.md.</translatorcomment>
        <translation>전통 조성 표기  (Am, Ebm, F#…)</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="429"/>
        <source>Traktor Open Key  (1m, 10m, 9d…)</source>
        <translatorcomment>Traktor Open Key kept as a product name (English); code values kept Latin.</translatorcomment>
        <translation>Traktor Open Key  (1m, 10m, 9d…)</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="445"/>
        <source>Energy Tag</source>
        <translation>에너지 태그</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="453"/>
        <source>Write energy level to Comment tag</source>
        <translatorcomment>energy level → 에너지 레벨; Comment tag → 코멘트 태그.</translatorcomment>
        <translation>에너지 레벨을 코멘트 태그에 기록</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="461"/>
        <source>Energy level written first</source>
        <translation>에너지 레벨을 먼저 기록</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="465"/>
        <source>When both energy and key are written to the comment, put energy first and key second.</source>
        <translation>에너지와 조성을 모두 코멘트에 기록할 때 에너지를 먼저, 조성을 나중에 기록합니다.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="471"/>
        <source>Format:</source>
        <translation>형식:</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="479"/>
        <source>Number only  (7)</source>
        <translation>숫자만  (7)</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="480"/>
        <source>With label  (Energy 7)</source>
        <translatorcomment>&quot;Energy 7&quot; left in English because it is the literal text written to the tag, not UI prose.</translatorcomment>
        <translation>레이블 포함  (Energy 7)</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="489"/>
        <source>Write mode:</source>
        <translation>기록 방식:</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="497"/>
        <source>Prepend to existing comment</source>
        <translation>기존 코멘트 앞에 추가</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="498"/>
        <source>Append to existing comment</source>
        <translation>기존 코멘트 뒤에 추가</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="499"/>
        <source>Replace existing comment</source>
        <translation>기존 코멘트 대체</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="519"/>
        <source>Write energy level to its own tag field</source>
        <translation>에너지 레벨을 전용 태그 필드에 기록</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="522"/>
        <source>Stores the energy where it can be read back exactly, instead of parsed out of the comment.</source>
        <translation>코멘트에서 파싱하는 대신, 에너지를 정확히 다시 읽을 수 있는 위치에 저장합니다.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="530"/>
        <source>Playlists</source>
        <translation>재생목록</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="539"/>
        <source>Duplicate tracks:</source>
        <translation>중복된 곡:</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="542"/>
        <source>Ask each time</source>
        <translation>매번 묻기</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="543"/>
        <source>Always add duplicates</source>
        <translation>항상 중복 추가</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="544"/>
        <source>Always skip duplicates</source>
        <translation>항상 중복 건너뛰기</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="556"/>
        <source>What happens when you add a track a playlist already contains. A set list can repeat a track on purpose, so this asks rather than deciding for you — pick one of the other options to stop being asked.</source>
        <translation>재생목록에 이미 있는 곡을 추가할 때의 동작이에요. 셋리스트에서는 같은 곡을 의도적으로 반복할 수도 있으므로, 대신 결정하지 않고 물어봐요. 묻지 않게 하려면 다른 옵션을 선택하세요.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="566"/>
        <source>Keep Scratch between sessions</source>
        <translation>세션 간에 Scratch 유지</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="573"/>
        <source>Scratch is the working list the Player opens on, and it starts empty each time you launch. Turn this on to have it reopen with whatever was in it — either way, Save Playlist keeps a copy.</source>
        <translation>Scratch는 플레이어가 처음 여는 작업 목록으로, 앱을 실행할 때마다 비어 있어요. 이전 내용을 그대로 열려면 이 옵션을 켜세요. 어느 쪽이든 ‘재생목록 저장’으로 사본을 남길 수 있어요.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="583"/>
        <source>Always use full paths in exported playlists</source>
        <translation>내보낸 재생목록에서 항상 전체 경로 사용</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="591"/>
        <source>Exported playlists use paths relative to the playlist file when the tracks sit beside it, so a folder you zip and send still works on someone else&apos;s machine. Turn this on to always write the full path instead.</source>
        <translation>곡이 재생목록 파일과 같은 위치에 있으면 내보낸 재생목록은 그 파일을 기준으로 한 상대 경로를 사용해요. 그래서 폴더를 압축해 보내도 다른 사람의 컴퓨터에서 그대로 작동합니다. 항상 전체 경로를 쓰려면 이 옵션을 켜세요.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="601"/>
        <source>Export All Playlists…</source>
        <translation>모든 재생목록 내보내기…</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="610"/>
        <source>Writes one folder of playlist files mirroring your tree — a backup any other app can read.</source>
        <translation>트리 구조를 그대로 반영한 재생목록 파일 폴더를 하나 만듭니다. 다른 어떤 앱에서도 읽을 수 있는 백업이에요.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="661"/>
        <source>Mixed in P now opens your audio files.</source>
        <translation>이제 오디오 파일이 Mixed in P에서 열립니다.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="672"/>
        <source>Mixed in P is not registered with Windows. Reinstalling it will register it.</source>
        <translation>Mixed in P가 Windows에 등록되어 있지 않습니다. 다시 설치하면 등록됩니다.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="677"/>
        <source>Windows Settings did not open. You can set this yourself there, under Apps → Default apps.</source>
        <translation>Windows 설정을 열지 못했습니다. ‘앱 → 기본 앱’에서 직접 설정할 수 있습니다.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="683"/>
        <source>Select an audio file in Finder, press Command-I, choose Mixed in P under “Open with”, then click Change All.</source>
        <translation>Finder에서 오디오 파일을 선택하고 Command-I를 누른 다음, ‘다음으로 열기’에서 Mixed in P를 선택하고 ‘모두 변경’을 클릭하세요.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="824"/>
        <source>Waveform color</source>
        <translation>파형 색상</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="856"/>
        <location filename="../widgets/settings_panel.py" line="869"/>
        <source>Restart required</source>
        <translation>재시작 필요</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="858"/>
        <source>The language change will take effect the next time you restart Mixed in P.</source>
        <translatorcomment>Product name &quot;Mixed in P&quot; kept Latin; object particle 를 after the vowel-final &quot;P&quot; (피). Flag for native review.</translatorcomment>
        <translation>언어 변경은 Mixed in P를 다음에 재시작할 때 적용돼요.</translation>
    </message>
    <message>
        <location filename="../widgets/settings_panel.py" line="871"/>
        <source>The theme change will take effect the next time you restart Mixed in P.</source>
        <translation>테마 변경은 Mixed in P를 다음에 재시작할 때 적용돼요.</translation>
    </message>
</context>
<context>
    <name>Sidebar</name>
    <message>
        <location filename="../widgets/sidebar.py" line="177"/>
        <source>Playlists</source>
        <translation>재생목록</translation>
    </message>
    <message>
        <location filename="../widgets/sidebar.py" line="188"/>
        <location filename="../widgets/sidebar.py" line="356"/>
        <source>Collapse sidebar</source>
        <translation>사이드바 접기</translation>
    </message>
    <message>
        <location filename="../widgets/sidebar.py" line="225"/>
        <source>Player</source>
        <translation>플레이어</translation>
    </message>
    <message>
        <location filename="../widgets/sidebar.py" line="226"/>
        <source>Rename</source>
        <translation>이름 변경</translation>
    </message>
    <message>
        <location filename="../widgets/sidebar.py" line="227"/>
        <source>Convert</source>
        <translation>변환</translation>
    </message>
    <message>
        <location filename="../widgets/sidebar.py" line="228"/>
        <source>Analyze</source>
        <translation>분석</translation>
    </message>
    <message>
        <location filename="../widgets/sidebar.py" line="231"/>
        <source>Keyboard</source>
        <translatorcomment>건반 (musical keyboard panel), not 키보드.</translatorcomment>
        <translation>건반</translation>
    </message>
    <message>
        <location filename="../widgets/sidebar.py" line="229"/>
        <source>Metadata</source>
        <translation>메타데이터</translation>
    </message>
    <message>
        <location filename="../widgets/sidebar.py" line="230"/>
        <source>Spectrum</source>
        <translation>스펙트럼</translation>
    </message>
    <message>
        <location filename="../widgets/sidebar.py" line="281"/>
        <location filename="../widgets/sidebar.py" line="289"/>
        <source>Settings</source>
        <translatorcomment>Settings → 설정 (Apple Korean standard).</translatorcomment>
        <translation>설정</translation>
    </message>
    <message>
        <location filename="../widgets/sidebar.py" line="293"/>
        <location filename="../widgets/sidebar.py" line="301"/>
        <source>History</source>
        <translatorcomment>History → 기록 (native, polished) over loanword 히스토리. Flag for native review.</translatorcomment>
        <translation>기록</translation>
    </message>
    <message>
        <location filename="../widgets/sidebar.py" line="356"/>
        <source>Expand sidebar</source>
        <translation>사이드바 펼치기</translation>
    </message>
    <message>
        <location filename="../widgets/sidebar.py" line="395"/>
        <source>Hide your playlists and show the navigation buttons again</source>
        <translation>재생목록을 숨기고 내비게이션 버튼을 다시 표시</translation>
    </message>
    <message>
        <location filename="../widgets/sidebar.py" line="397"/>
        <source>Show your playlists here in place of the navigation buttons</source>
        <translation>내비게이션 버튼 대신 여기에 재생목록 표시</translation>
    </message>
    <message>
        <location filename="../widgets/sidebar.py" line="450"/>
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
        <location filename="../widgets/spectrum_panel.py" line="84"/>
        <source>Drop a single audio file to view its spectrum</source>
        <translation>오디오 파일 하나를 끌어다 놓으면 스펙트럼을 볼 수 있어요</translation>
    </message>
</context>
<context>
    <name>SpectrumPanel</name>
    <message>
        <location filename="../widgets/spectrum_panel.py" line="255"/>
        <source>Spectrum</source>
        <translation>스펙트럼</translation>
    </message>
    <message>
        <location filename="../widgets/spectrum_panel.py" line="260"/>
        <source>Drop a single audio file to see its acoustic spectrum. Frequency runs bottom (0 Hz) to top (Nyquist); time runs left to right; colour shows magnitude. Handy for spotting lossy-encode low-pass cutoffs.</source>
        <translatorcomment>Technical terms: frequency → 주파수, Nyquist → 나이퀴스트, magnitude → 크기, lossy-encode → 손실 인코딩, low-pass → 저역 통과, cutoff → 컷오프. Hz kept Latin. 해요체. Flag for native review.</translatorcomment>
        <translation>오디오 파일 하나를 끌어다 놓으면 음향 스펙트럼을 볼 수 있어요. 주파수는 아래(0 Hz)에서 위(나이퀴스트)로, 시간은 왼쪽에서 오른쪽으로 흐르고, 색상은 크기를 나타내요. 손실 인코딩의 저역 통과 컷오프를 찾을 때 유용해요.</translation>
    </message>
    <message>
        <source>File</source>
        <translation type="vanished">파일</translation>
    </message>
    <message>
        <location filename="../widgets/spectrum_panel.py" line="314"/>
        <source>Sample rate</source>
        <translatorcomment>DSP term → 샘플 레이트 (not the producer &quot;sample&quot;). Consistent with the Conversion panel. Flag for native review.</translatorcomment>
        <translation>샘플 레이트</translation>
    </message>
    <message>
        <location filename="../widgets/spectrum_panel.py" line="315"/>
        <source>Key</source>
        <translatorcomment>Musical key → 조성. Flag for native review.</translatorcomment>
        <translation>조성</translation>
    </message>
    <message>
        <location filename="../widgets/spectrum_panel.py" line="316"/>
        <source>BPM</source>
        <translation>BPM</translation>
    </message>
    <message>
        <location filename="../widgets/spectrum_panel.py" line="336"/>
        <source>Sensitivity:</source>
        <translation>감도:</translation>
    </message>
    <message>
        <location filename="../widgets/spectrum_panel.py" line="347"/>
        <location filename="../widgets/spectrum_panel.py" line="429"/>
        <location filename="../widgets/spectrum_panel.py" line="444"/>
        <source>{0} dB range</source>
        <translation>{0} dB 범위</translation>
    </message>
    <message>
        <location filename="../widgets/spectrum_panel.py" line="403"/>
        <location filename="../widgets/spectrum_panel.py" line="404"/>
        <source>Analyzing…</source>
        <translation>분석 중…</translation>
    </message>
    <message>
        <location filename="../widgets/spectrum_panel.py" line="493"/>
        <source>Could not analyze this file.</source>
        <translation>이 파일을 분석할 수 없어요.</translation>
    </message>
    <message>
        <location filename="../widgets/spectrum_panel.py" line="494"/>
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
<context>
    <name>run_app</name>
    <message>
        <location filename="../app.py" line="186"/>
        <source>Mixed in P is already running</source>
        <translation>Mixed in P이 이미 실행 중입니다</translation>
    </message>
    <message>
        <location filename="../app.py" line="187"/>
        <source>The running copy didn&apos;t respond, so those files weren&apos;t opened. Bring it to the front and add them there.</source>
        <translation>실행 중인 사본이 응답하지 않아 해당 파일을 열지 못했습니다. 실행 중인 창을 앞으로 가져온 후 거기에서 추가하세요.</translation>
    </message>
</context>
</TS>
