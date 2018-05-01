package main

import (
	"bufio"
	"encoding/hex"
	"fmt"
	"math/rand"
	"net/http"
	"os"
	"sort"
	"strings"
	"time"

	"github.com/kennygrant/sanitize"
	"github.com/kjk/u"
	"mvdan.cc/xurls"
	"github.com/sourcegraph/syntaxhighlight"
)

const (
	noteSeparator  = "---"
	codeBlockStart = "```"
)

var (
	notesDays       []*notesForDay
	notesTagToNotes map[string][]*note
	// maps unique id of the note (from Id: ${id} metadata) to the note
	notesIDToNote  map[string]*note
	notesTagCounts []tagWithCount
	notesAllNotes  []*note

	notesWeekStartDayToNotes map[string][]*note
	notesWeekStarts          []string
	nTotalNotes              int
)

type tagWithCount struct {
	Tag   string
	Count int
}

type noteMetadata struct {
	ID    string
	Title string
}

type note struct {
	Day            time.Time
	DayStr         string // in format "2006-01-02"
	DayWithNameStr string // in format "2006-01-02 Mon"
	ID             string
	Title          string
	URL            string // in format /dailynotes/note/${id}-${title}
	HTMLBody       string
	Tags           []string
}

type notesForDay struct {
	Day    time.Time
	DayStr string
	Notes  []*note
}

type modelNotesForWeek struct {
	Notes         []*note
	TotalNotes    int
	TagCounts     []tagWithCount
	WeekStartDay  string
	NextWeek      string
	PrevWeek      string
	AnalyticsCode string
}

func lastLineEmpty(lines []string) bool {
	if len(lines) == 0 {
		return false
	}
	lastIdx := len(lines) - 1
	line := lines[lastIdx]
	return len(line) == 0
}

func removeLastLine(lines []string) []string {
	lastIdx := len(lines) - 1
	return lines[:lastIdx]
}

func findWordEnd(s string, start int) int {
	for i := start; i < len(s); i++ {
		c := s[i]
		if c == ' ' {
			return i + 1
		}
	}
	return -1
}

// TODO: must not remove spaces from start
func collapseMultipleSpaces(s string) string {
	for {
		s2 := strings.Replace(s, "  ", " ", -1)
		if s2 == s {
			return s

		}
		s = s2
	}
}

// remove #tag from start and end
func removeHashTags(s string) (string, []string) {
	var tags []string
	defer func() {
		for i, tag := range tags {
			tags[i] = strings.ToLower(tag)
		}
	}()

	// remove hashtags from start
	for strings.HasPrefix(s, "#") {
		idx := findWordEnd(s, 0)
		if idx == -1 {
			tags = append(tags, s[1:])
			return "", tags
		}
		tags = append(tags, s[1:idx-1])
		s = strings.TrimLeft(s[idx:], " ")
	}

	// remove hashtags from end
	s = strings.TrimRight(s, " ")
	for {
		idx := strings.LastIndex(s, "#")
		if idx == -1 {
			return s, tags
		}
		// tag from the end must not have space after it
		if -1 != findWordEnd(s, idx) {
			return s, tags
		}
		// tag from the end must start at the beginning of line
		// or be proceded by space
		if idx > 0 && s[idx-1] != ' ' {
			return s, tags
		}
		tags = append(tags, s[idx+1:])
		s = strings.TrimRight(s[:idx], " ")
	}
}

func buildBodyFromLines(lines []string) (string, []string) {
	var resTags []string

	for i, line := range lines {
		line, tags := removeHashTags(line)
		lines[i] = line
		resTags = append(resTags, tags...)
	}
	resTags = u.RemoveDuplicateStrings(resTags)

	// collapse multiple empty lines into single empty line
	// and remove lines that are just #hashtags
	currWrite := 1
	for i := 1; i < len(lines); i++ {
		prev := lines[currWrite-1]
		curr := lines[i]
		if len(prev) == 0 && len(curr) == 0 {
			// skips the current line because we don't advance currWrite
			continue
		}

		lines[currWrite] = curr
		currWrite++
	}
	lines = lines[:currWrite]

	if len(lines) == 0 {
		return "", resTags
	}

	// remove empty lines from beginning
	for len(lines[0]) == 0 {
		lines = lines[1:]
	}

	// remove empty lines from end
	for lastLineEmpty(lines) {
		lines = removeLastLine(lines)
	}
	return strings.Join(lines, "\n"), resTags
}

// given lines, extracts metadata information from lines that are:
// Id: $id
// Title: $title
// Returns new lines with metadata lines removed
func extractMetaDataFromLines(lines []string) ([]string, noteMetadata) {
	var res noteMetadata
	writeIdx := 0
	for i, s := range lines {
		idx := strings.Index(s, ":")
		skipLine := false
		if -1 != idx {
			name := strings.ToLower(s[:idx])
			val := strings.TrimSpace(s[idx+1:])
			switch name {
			case "id":
				res.ID = val
				skipLine = true
			case "title":
				res.Title = val
				skipLine = true
			}
		}
		if skipLine || writeIdx == i {
			continue
		}
		lines[writeIdx] = lines[i]
		writeIdx++
	}
	u.PanicIf(res.ID == "", "note has no Id:. Note: %s\n", strings.Join(lines, "\n"))
	return lines[:writeIdx], res
}

// there are no guarantees in life, but this should be pretty unique string
func genRandomString() string {
	var a [20]byte
	_, err := rand.Read(a[:])
	if err == nil {
		return hex.EncodeToString(a[:])
	}
	return fmt.Sprintf("__--##%d##--__", rand.Int63())
}

func noteToHTML(s string) string {
	urls := xurls.Strict().FindAllString(s, -1)
	urls = u.RemoveDuplicateStrings(urls)

	// sort by length, longest first, so that we correctly convert
	// urls to hrefs when there are 2 urls like http://foo.com
	// and http://foo.com/longer
	sort.Slice(urls, func(i, j int) bool {
		return len(urls[i]) > len(urls[j])
	})
	// this is a two-step url -> random_unique_string,
	// random_unique_string -> url replacement to prevent
	// double-escaping if we have 2 urls like: foo.bar.com and bar.com
	urlToAnchor := make(map[string]string)

	for _, url := range urls {
		anchor := genRandomString()
		urlToAnchor[url] = anchor
		s = strings.Replace(s, url, anchor, -1)
	}

	for _, url := range urls {
		replacement := fmt.Sprintf(`<a href="%s">%s</a>`, url, url)
		anchor := urlToAnchor[url]
		s = strings.Replace(s, anchor, replacement, -1)
	}

	s, _ = sanitize.HTMLAllowing(s, []string{"a"})
	return s
}

// returns new lines and a mapping of string => html as flattened string array
func extractCodeSnippets(lines []string) ([]string, []string) {
	var resLines []string
	var anchors []string
	codeLineStart := -1
	for i, s := range lines {
		isCodeLine := strings.HasPrefix(s, codeBlockStart)
		if isCodeLine {
			if codeLineStart == -1 {
				// this is a beginning of new code block
				codeLineStart = i
			} else {
				// end of the code block
				//lang := strings.TrimPrefix(lines[codeLineStart], codeBlockStart)
				codeLines := lines[codeLineStart+1 : i]
				codeLineStart = -1
				code := strings.Join(codeLines, "\n")
				codeHTML, err := syntaxhighlight.AsHTML([]byte(code))
				u.PanicIfErr(err)
				anchor := genRandomString()
				resLines = append(resLines, anchor)
				anchors = append(anchors, anchor, string(codeHTML))
			}
		} else {
			if codeLineStart == -1 {
				resLines = append(resLines, s)
			}
		}
	}
	// TODO: could append unclosed lines
	u.PanicIf(codeLineStart != -1)

	return resLines, anchors
}

func newNote(lines []string) *note {
	nTotalNotes++
	lines, meta := extractMetaDataFromLines(lines)
	lines, codeReplacements := extractCodeSnippets(lines)
	s, tags := buildBodyFromLines(lines)
	body := noteToHTML(s)
	n := len(codeReplacements) / 2
	for i := 0; i < n; i++ {
		anchor := codeReplacements[i*2]
		codeHTML := `<pre class="note-code">` + codeReplacements[i*2+1] + `</pre>`
		body = strings.Replace(body, anchor, codeHTML, -1)
	}
	return &note{
		Tags:     tags,
		HTMLBody: body,
		ID:       meta.ID,
		Title:    meta.Title,
	}
}

func linesToNotes(lines []string) []*note {
	// parts are separated by "---" line
	var res []*note
	var curr []string
	for _, line := range lines {
		if line == noteSeparator {
			if len(curr) > 0 {
				part := newNote(curr)
				res = append(res, part)
			}
			curr = nil
		} else {
			curr = append(curr, line)
		}
	}
	if len(curr) > 0 {
		part := newNote(curr)
		res = append(res, part)
	}
	return res
}

func readNotes(path string) error {
	notesTagToNotes = make(map[string][]*note)
	notesWeekStartDayToNotes = make(map[string][]*note)
	notesIDToNote = make(map[string]*note)
	notesWeekStarts = nil
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	scanner := bufio.NewScanner(f)
	var notes []*notesForDay
	var curr *notesForDay
	var lines []string

	seenDays := make(map[string]bool)

	for scanner.Scan() {
		s := strings.TrimRight(scanner.Text(), "\n\r\t ")
		day, err := time.Parse("2006-01-02", s)

		if err != nil {
			// first line must be a valid new day
			u.PanicIf(curr == nil)
			lines = append(lines, s)
			continue
		}

		// this is a new day
		if curr != nil {
			curr.Notes = linesToNotes(lines)
			notes = append(notes, curr)
		}
		u.PanicIf(seenDays[s], "duplicate day: %s", s)
		seenDays[s] = true
		curr = &notesForDay{
			Day:    day,
			DayStr: s,
		}
		lines = nil
	}
	curr.Notes = linesToNotes(lines)
	notesDays = append(notes, curr)

	// verify they are in chronological order
	for i := 1; i < len(notesDays); i++ {
		notesForDay := notesDays[i-1]
		notesForPrevDay := notesDays[i]
		diff := notesForDay.Day.Sub(notesForPrevDay.Day)
		if diff < 0 {
			return fmt.Errorf("Note '%s' should be later than '%s'", notesForDay.DayStr, notesForPrevDay.DayStr)
		}
	}

	nNotes := 0
	// update date and id on notes
	for _, day := range notesDays {
		weekStartTime := calcWeekStart(day.Day)
		weekStartDay := weekStartTime.Format("2006-01-02")
		for _, note := range day.Notes {
			notesAllNotes = append(notesAllNotes, note)
			nNotes++
			id := note.ID
			u.PanicIf(notesIDToNote[id] != nil, "duplicate note id: %s", id)
			notesIDToNote[id] = note
			note.Day = day.Day
			note.DayStr = day.Day.Format("2006-01-02")
			note.DayWithNameStr = day.Day.Format("2006-01-02 Mon")
			note.URL = "/dailynotes/note/" + id
			if note.Title != "" {
				note.URL += "-" + urlify(note.Title)
			}
			for _, tag := range note.Tags {
				a := notesTagToNotes[tag]
				a = append(a, note)
				notesTagToNotes[tag] = a
			}
			a := notesWeekStartDayToNotes[weekStartDay]
			a = append(a, note)
			notesWeekStartDayToNotes[weekStartDay] = a
		}
	}
	for day := range notesWeekStartDayToNotes {
		notesWeekStarts = append(notesWeekStarts, day)
	}
	var tags []string
	for tag := range notesTagToNotes {
		tags = append(tags, tag)
	}
	sort.Strings(tags)
	for _, tag := range tags {
		count := len(notesTagToNotes[tag])
		tc := tagWithCount{
			Tag:   tag,
			Count: count,
		}
		notesTagCounts = append(notesTagCounts, tc)
	}

	sort.Strings(notesWeekStarts)
	reverseStringArray(notesWeekStarts)
	fmt.Printf("Read %d notes in %d days and %d weeks\n", nNotes, len(notesDays), len(notesWeekStarts))
	return scanner.Err()
}

func reverseStringArray(a []string) {
	n := len(a) / 2
	for i := 0; i < n; i++ {
		end := len(a) - i - 1
		a[i], a[end] = a[end], a[i]
	}
}

// given time, return time on start of week (monday)
func calcWeekStart(t time.Time) time.Time {
	// wd is 1 to 7
	wd := t.Weekday()
	dayOffset := time.Duration((wd - 1)) * time.Hour * -24
	return t.Add(dayOffset)
}

// /dailynotes
func handleNotesIndex(w http.ResponseWriter, r *http.Request) {
	weekStart := notesWeekStarts[0]
	notes := notesWeekStartDayToNotes[weekStart]
	var nextWeek string
	if len(notesWeekStarts) > 1 {
		nextWeek = notesWeekStarts[1]
	}
	model := &modelNotesForWeek{
		Notes:         notes,
		TagCounts:     notesTagCounts,
		TotalNotes:    nTotalNotes,
		WeekStartDay:  weekStart,
		AnalyticsCode: analyticsCode,
		NextWeek:      nextWeek,
	}
	serveTemplate(w, tmplNotesWeek, model)
}

// /dailynotes/week/${day} : week starting with a given day
func handleNotesWeek(w http.ResponseWriter, r *http.Request) {
	uri := r.RequestURI
	weekStart := strings.TrimPrefix(uri, "/dailynotes/week/")
	notes := notesWeekStartDayToNotes[weekStart]
	if len(notes) == 0 {
		serve404(w, r)
		return
	}
	var nextWeek, prevWeek string
	for idx, ws := range notesWeekStarts {
		if ws != weekStart {
			continue
		}
		if idx > 0 {
			prevWeek = notesWeekStarts[idx-1]
		}
		lastIdx := len(notesWeekStarts) - 1
		if idx+1 <= lastIdx {
			nextWeek = notesWeekStarts[idx+1]
		}
		break
	}
	model := &modelNotesForWeek{
		Notes:         notes,
		TagCounts:     notesTagCounts,
		WeekStartDay:  weekStart,
		NextWeek:      nextWeek,
		PrevWeek:      prevWeek,
		AnalyticsCode: analyticsCode,
	}
	serveTemplate(w, tmplNotesWeek, model)
}

func findNotesForDay(dayStr string) *notesForDay {
	for _, d := range notesDays {
		if dayStr == d.DayStr {
			return d
		}
	}
	return nil
}

// /worklog
func handleWorkLog(w http.ResponseWriter, r *http.Request) {
	// originally /dailynotes was under /worklog
	http.Redirect(w, r, "/dailynotes", http.StatusMovedPermanently)
}

// /dailynotes/note/${id}-${title}
func handleNotesNote(w http.ResponseWriter, r *http.Request) {
	uri := r.RequestURI
	s := strings.TrimPrefix(uri, "/dailynotes/note/")
	parts := strings.SplitN(s, "-", 2)
	noteID := parts[0]
	aNote := notesIDToNote[noteID]
	if aNote == nil {
		serve404(w, r)
		return
	}

	weekStartTime := calcWeekStart(aNote.Day)
	weekStartDay := weekStartTime.Format("2006-01-02")
	model := struct {
		WeekStartDay  string
		Note          *note
		AnalyticsCode string
	}{
		WeekStartDay:  weekStartDay,
		Note:          aNote,
		AnalyticsCode: analyticsCode,
	}
	serveTemplate(w, tmplNotesNote, model)
}

// /dailynotes/tag/${tag} :
func handleNotesTag(w http.ResponseWriter, r *http.Request) {
	uri := r.RequestURI
	tag := strings.TrimPrefix(uri, "/dailynotes/tag/")
	notes := notesTagToNotes[tag]

	if len(notes) == 0 {
		serve404(w, r)
		return
	}

	model := struct {
		Notes         []*note
		TagCounts     []tagWithCount
		Tag           string
		AnalyticsCode string
	}{
		Notes:         notes,
		TagCounts:     notesTagCounts,
		Tag:           tag,
		AnalyticsCode: analyticsCode,
	}
	serveTemplate(w, tmplNotesTag, model)
}
