import { parseTranscript } from './engine/lib/transcript.mjs';
import { auditGraduation } from './engine/lib/graduation.mjs';
import { getHandbookYears } from './engine/lib/handbooks.mjs';
import { findSchedules, explainScheduleFailure } from './engine/lib/schedule.mjs';
import { mergeCourseRows, toCourse } from './engine/lib/kupis.mjs';

// This runner handles local inputs. A calculation cannot start a school fetch.
globalThis.fetch = async () => { throw new Error('NETWORK_DISABLED'); };
const MAX_INPUT = 4 * 1024 * 1024;
const days = ['월', '화', '수', '목', '금'];
const grades = ['A+', 'A', 'B+', 'B', 'C+', 'C', 'D+', 'D', 'F', 'P', 'NP'];

function object(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('객체 형식의 입력이 필요해요.');
  return value;
}
function string(value, max = 200) {
  if (typeof value !== 'string' || !value.trim() || value.length > max) throw new Error('필수 문자열을 확인해 주세요.');
  return value;
}
function number(value, min, max) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max) throw new Error('숫자 범위를 확인해 주세요.');
  return value;
}
function array(value, max) {
  if (!Array.isArray(value) || value.length > max) throw new Error('목록의 형식이나 개수를 확인해 주세요.');
  return value;
}
function strings(value, max = 100) {
  return array(value ?? [], max).map((item) => string(item));
}
function transcriptRecord(value) {
  const record = object(value);
  const admissionYear = record.admissionYear ?? Number(string(record.studentId).slice(0, 4));
  number(admissionYear, 1900, 2200);
  const courses = array(record.courses, 500).map((item) => {
    const row = object(item);
    const grade = string(row.grade);
    if (!grades.includes(grade)) throw new Error('인식할 수 없는 성적이 있어요. 원본 성적표를 확인해 주세요.');
    return { year: number(row.year, 1900, 2200), semester: string(row.semester),
      category: string(row.category), code: string(row.code), name: string(row.name),
      credits: number(row.credits, 0, 30), grade };
  });
  // Duplicate attempts need the school's retake decision, not summed credits.
  const codes = courses.map((item) => item.code);
  if (new Set(codes).size !== codes.length) throw new Error('중복·재이수 과목이 있어요. 학교에서 인정한 최종 성적으로 정리해 주세요.');
  return { studentId: '', name: '', department: string(record.department), admissionYear,
    studentYear: number(record.studentYear ?? 0, 0, 20), totalCredits: number(record.totalCredits, 0, 1000),
    gpa: number(record.gpa ?? 0, 0, 4.5), lastSemesterGpa: number(record.lastSemesterGpa ?? 0, 0, 4.5), courses };
}
function audit(value) {
  const record = transcriptRecord(value);
  const available = getHandbookYears();
  if (!available.includes(record.admissionYear)) throw new Error(`${record.admissionYear}년 입학 요람이 준비되지 않았어요. 해당 연도 요람을 먼저 추가해 주세요.`);
  const graduation = auditGraduation(record);
  if (!graduation || !graduation.credits || !graduation.required.length) throw new Error('이 학과의 졸업요건을 충분히 확인하지 못했어요. 입학연도·학과·요람을 확인해 주세요.');
  return { profile: { department: record.department, admissionYear: record.admissionYear },
    courses: record.courses, graduation, warnings: ['요람 기준 참고 결과예요. 복수전공·편입·재이수 등 개별 인정은 학사 담당자에게 확인해 주세요.'] };
}
function meeting(value) {
  const row = object(value);
  if (!days.includes(row.day)) throw new Error('수업 요일을 확인해 주세요.');
  const start = number(row.start, 0, 24);
  const end = number(row.end, 0, 24);
  if (start >= end) throw new Error('수업 시작·종료 시간을 확인해 주세요.');
  return { day: row.day, start, end };
}
function schedule(input) {
  const courses = array(input.courses, 100).map((value) => {
    const row = object(value);
    const online = row.deliveryMode === '이러닝';
    const meetings = row.meetings ? array(row.meetings, 20).map(meeting) : online ? [] : [meeting(row)];
    if (!online && !meetings.length) throw new Error('대면 수업의 시간을 입력해 주세요.');
    const first = meetings[0] ?? { day: '월', start: 0, end: 0 };
    if (row.fixed !== undefined && typeof row.fixed !== 'boolean') throw new Error('고정 과목 여부를 확인해 주세요.');
    return { id: string(row.id), name: string(row.name), group: string(row.group),
      credits: number(row.credits, 0, 30), ...first, meetings, color: 1, fixed: row.fixed ?? false,
      professor: row.professor === undefined ? '' : string(row.professor),
      category: row.category === undefined ? '' : string(row.category), deliveryMode: online ? '이러닝' : '대면' };
  });
  if (new Set(courses.map((row) => row.id)).size !== courses.length) throw new Error('중복 분반 ID가 있어요.');
  const raw = object(input.preferences ?? {});
  for (const key of ['noMorning', 'lunch']) if (raw[key] !== undefined && typeof raw[key] !== 'boolean') throw new Error('선호 조건은 true/false로 지정해 주세요.');
  const freeDays = strings(raw.freeDays, 5);
  if (freeDays.some((day) => !days.includes(day))) throw new Error('공강 요일을 확인해 주세요.');
  const priorities = object(raw.coursePriorities ?? {});
  if (Object.values(priorities).some((v) => v !== '!' && !/^[1-9]$/.test(v))) throw new Error('과목 우선순위는 ! 또는 1~9로 지정해 주세요.');
  const preferences = { freeDays, noMorning: raw.noMorning ?? false, lunch: raw.lunch ?? false,
    preferredProfessors: strings(raw.preferredProfessors), avoidedProfessors: strings(raw.avoidedProfessors),
    preferredCourses: strings(raw.preferredCourses), preferredCategories: strings(raw.preferredCategories),
    coursePriorities: priorities,
    blockedSlots: array(raw.blockedSlots ?? [], 120).map((slot) => {
      object(slot);
      if (!days.includes(slot.day)) throw new Error('제외 시간의 요일을 확인해 주세요.');
      return { day: slot.day, hour: number(slot.hour, 0, 23) };
    }) };
  const results = findSchedules(courses, preferences, number(input.maxCredits ?? 21, 0, 60));
  return { schedules: results, failure: results.length ? null : explainScheduleFailure(courses, preferences),
    warnings: ['상위 5개 후보예요. 실제 개설·좌석·수강 제한은 최신 학교 안내로 확인해 주세요.'] };
}
function catalog(input) {
  const rows = array(input.rows, 5000).map((value) => {
    const row = object(value);
    const clean = {};
    for (const key of ['lec_no', 'lec_nm', 'isu_nm', 'pnt', 'lec_tm', 'prof', 'haksu_id', 'clss_no',
      'tlsn_lmt_rcnt', 'tlsn_rcnt', 'clse_fg', 'params', 'sourceMenu', 'sourceLectCd', 'sourceDepartment']) {
      if (typeof row[key] !== 'string' || row[key].length > 2000) throw new Error(`과목 목록의 ${key} 값을 확인해 주세요.`);
      clean[key] = row[key];
    }
    for (const key of ['shyr', 'sust_list', 'sugang_remk', 'remk', 'sourceArea']) {
      if (row[key] !== undefined) clean[key] = string(row[key], 2000);
    }
    return clean;
  });
  return { courses: mergeCourseRows(rows.filter((row) => row.clse_fg === '0')).map(toCourse) };
}

try {
  let size = 0;
  const chunks = [];
  for await (const chunk of process.stdin) {
    size += chunk.length;
    if (size > MAX_INPUT) throw new Error('입력은 4MB 이하여야 해요.');
    chunks.push(chunk);
  }
  const input = object(JSON.parse(Buffer.concat(chunks).toString('utf8')));
  let data;
  switch (input.action) {
    case 'status': data = { availableHandbookYears: getHandbookYears(), actions: ['transcript', 'audit', 'schedule', 'catalog'], network: false }; break;
    case 'transcript': data = audit(parseTranscript(string(input.text, MAX_INPUT))); break;
    case 'audit': data = audit(input.transcript); break;
    case 'schedule': data = schedule(input); break;
    case 'catalog': data = catalog(input); break;
    default: throw new Error('지원하지 않는 GradKUya 작업이에요.');
  }
  process.stdout.write(JSON.stringify({ status: 'READY', data }));
} catch (error) {
  const message = error instanceof SyntaxError ? '입력 JSON을 확인해 주세요.' : error.message;
  process.stdout.write(JSON.stringify({ status: 'ERROR', error: { code: 'GRADKUYA_INVALID', message } }));
  process.exitCode = 1;
}
