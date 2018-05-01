package main

import (
	"net/http"
)

/*
var tmplCrashesRss = template.Must(template.New("crashesrss.html").Parse(`
  <p>{{ len .Crashes }} crashes for {{ .Day }}:</p>
  {{ $appName := .AppName }}
  <table>
    {{ range .Crashes }}
      <tr>
        <td><a href="/app/crashshow?crash_id={{ .Id }}">{{ .Id }}</a></td>
        <td>{{ .Version }}</td>
        <td><a href="/app/crashes?app_name={{$appName}}&crashing_line={{.CrashingLine}}">{{ .ShortCrashingLine }}</a></td>
      </tr>
    {{ end }}
  </table>
`))

// /app/crashesrss?app_name=${appName}
func handleCrashesRss(w http.ResponseWriter, r *http.Request) {
	appName := getTrimmedFormValue(r, "app_name")
	app := storeCrashes.GetAppByName(appName)
	if app == nil {
		logger.Errorf("handleCrashesRss(): invalid app %q", appName)
		httpNotFound(w, r)
		return
	}
	// to minimize the number of times rss reader updates the entries, we
	// don't show crashes for today i.e. if first day is the same time as
	// current time, we skip it
	appDisplay := NewAppDisplay(app, true)
	pubDate := time.Now()
	firstDayIdx := -1
	if len(appDisplay.Days) > 0 {
		firstDayIdx = 0
		todayDay := time.Now().Format("2006-01-02")
		if todayDay == appDisplay.Days[1].Day {
			firstDayIdx = 1
		}
	}
	if firstDayIdx != -1 {
		pubDate, _ = time.Parse("2006-01-02", appDisplay.Days[firstDayIdx].Day)
	}

	feed := &atom.Feed{
		Title:   fmt.Sprintf("Crashes %s", appName),
		Link:    fmt.Sprintf("http://3cham.io/app/crashesrss?app_name=%s", appName),
		PubDate: pubDate}
	baseURL := fmt.Sprintf("http://3cham.io/app/crashes?app_name=%s", appName)
	if firstDayIdx == -1 {
		e := &atom.Entry{
			Title:   fmt.Sprintf("Crashes for %s", appName),
			Link:    baseURL,
			Content: fmt.Sprintf("There are no crashes for %s yet", appName),
			PubDate: pubDate}
		feed.AddEntry(e)
	} else {
		maxDays := 10
		for i := firstDayIdx; i < len(appDisplay.Days) && maxDays > 0; maxDays-- {
			day := appDisplay.Days[i].Day
			crashes := appDisplay.Days[i].Crashes
			model := struct {
				Crashes []*Crash
				Day     string
				AppName string
			}{
				Day:     day,
				AppName: appName,
				Crashes: crashes,
			}
			var buf bytes.Buffer
			tmplCrashesRss.Execute(&buf, model)
			html := string(buf.Bytes())
			pubDate, _ = time.Parse("2006-01-02", day)
			e := &atom.Entry{
				Title:   fmt.Sprintf("%d %s crashes on %s", len(crashes), appName, day),
				Link:    fmt.Sprintf("%s&day=%s", baseURL, day),
				Content: html,
				PubDate: pubDate}
			feed.AddEntry(e)
			i++
		}
	}

	s, err := feed.GenXml()
	if err != nil {
		s = []byte("Failed to generate XML feed")
	}
	w.Write(s)
}
*/

// POST /app/crashsubmit?appname=${appName}&file=${crashData}
func handleCrashSubmit(w http.ResponseWriter, r *http.Request) {
	// this moved to kjktools.org, return empty response
	w.Write([]byte(""))
}
