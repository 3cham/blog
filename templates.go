package main

import (
	"html/template"
	"bytes"
	"net/http"
	"path/filepath"
	"strconv"

	"github.com/kjk/u"
)

var (
	tmplMainPage         = "mainpage.tmpl.html"
	tmplArticle          = "article.tmpl.html"
	tmplArchive          = "archive.tmpl.html"
	tmplNotesWeek        = "notes_week.tmpl.html"
	tmplNotesTag         = "notes_tag.tmpl.html"
	tmplNotesNote        = "notes_note.tmpl.html"
	tmplGenerateUniqueID = "generate-unique-id.tmpl.html"
	tmpl404              = "404.tmpl.html"
	templateNames        = []string{
		tmplMainPage,
		tmplArticle,
		tmplArchive,
		tmplNotesWeek,
		tmplNotesTag,
		tmplNotesNote,
		tmplGenerateUniqueID,
		tmpl404,
		"analytics.tmpl.html",
		"page_navbar.tmpl.html",
		"documents.tmpl.html",
		"tagcloud.tmpl.js",
	}
	templatePaths   []string
	templates       *template.Template
	reloadTemplates = true

	// dirs to search when looking for templates
	tmplDirs = []string{
		"tmpl",
		"www",
		filepath.Join("www", "tools"),
		filepath.Join("www", "static"),
	}
)

func findTemplate(name string) string {
	for _, dir := range tmplDirs {
		path := filepath.Join(dir, name)
		if u.FileExists(path) {
			return path
		}
	}
	u.PanicIf(true, "didn't find tamplate %s in dirs %v", name, tmplDirs)
	return ""
}

func getTemplates() *template.Template {
	if reloadTemplates || (nil == templates) {
		if 0 == len(templatePaths) {
			for _, name := range templateNames {
				path := findTemplate(name)
				templatePaths = append(templatePaths, path)
			}
		}
		templates = template.Must(template.ParseFiles(templatePaths...))
	}
	return templates
}

func serveTemplate(w http.ResponseWriter, templateName string, model interface{}) bool {
	var buf bytes.Buffer
	if err := getTemplates().ExecuteTemplate(&buf, templateName, model); err != nil {
		logger.Errorf("Failed to execute template %q, error: %s", templateName, err)
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return false
	}

	// at this point we ignore error
	w.Header().Set("Content-Length", strconv.Itoa(len(buf.Bytes())))
	w.Write(buf.Bytes())
	return true
}
