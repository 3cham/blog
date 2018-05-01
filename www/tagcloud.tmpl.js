function $(id) {
    if (id[0] === '#') {
        id = id.substr(1);
    }
    return document.getElementById(id);
}

function showById(id) {
    $('#' + id).removeClass("invisible").addClass("visible");
}

function hideById(id) {
    $('#' + id).removeClass("visible").addClass("invisible");
}

var articles_json = null;
var TAGS_IDX = 0;

function a(url, txt) {
    return '<a href="' + url + '">' + txt + "</a>";
}

function span(txt, cls) {
    return '<span class="' + cls + '">' + txt + '</span>';
}

function tagUrl(url, tag, count) {
    return span(a(url, tag) + ' ' + span('(' + count + ')', "light"), "nowrap") + ' ';
}

function tagUrl2(url, tag, count) {
    return span(a(url, tag) + ' ' + span(count, "light"), "nowrap") + ' ';
}

function build_tags_hash() {
    var all_tags = {};
    var tags, i, j, tag_count;

    for (i = 0; i < articles_json.length; i++) {
        tags = articles_json[i][TAGS_IDX];
        var n = 0;
        if (tags != null) {
            n = tags.length
        }
        for (j = 0; j < n; j++) {
            tag = tags[j];
            tag_count = all_tags[tag];
            if (undefined == tag_count) {
                tag_count = 1;
            } else {
                tag_count += 1;
            }
            all_tags[tag] = tag_count;
        }
    }
    return all_tags;
}

function sort_tags(all_tags) {
    var all_tags_arr = [],
        tag;

    for (tag in all_tags) {
        all_tags_arr.push(tag);
    }

    all_tags_arr.sort(function(x, y) {
        var a = String(x).toUpperCase();
        var b = String(y).toUpperCase();
        if (a > b)
            return 1
        if (a < b)
            return -1
        return 0;
    });
    return all_tags_arr;
}

function genTagCloudHtml() {
    var tag, tags, tag_count;
    var tags = build_tags_hash();
    var tags_arr = sort_tags(tags);

    var lines = [];
    lines.push(tagUrl("/archives.html", "all", articles_json.length));
    for (var i = 0; i < tags_arr.length; i++) {
        tag = tags_arr[i];
        tag_count = tags[tag];
        lines.push(tagUrl("/tag/" + tag, tag, tag_count));
    }
    return lines.join("");
}

function genTagCloudHtml2() {
    var tag, tags, tag_count;
    var tags = build_tags_hash();
    var tags_arr = sort_tags(tags);

    var lines = [];
    lines.push(tagUrl2("/archives.html", "all", articles_json.length));
    for (i = 0; i < tags_arr.length; i++) {
        tag = tags_arr[i];
        tag_count = tags[tag];
        lines.push(tagUrl2("/tag/" + tag, tag, tag_count));
    }
    return lines.join("");
}
