tmpl = """<html>
<head>
<style type="text/css">

body, table {
	font-family: "Lucida Grande", sans-serif;
	font-size: 12px;
	font-size: 8pt;
}

table {
	color: #444;
}

td {
	font-family: consolas, menlo, monospace;
}

.header {
	color: #420066;
	color: #0000ff;
	font-style: italic;
}

.line {
	border-bottom: 1px dotted #ccc;
}

.big {
	font-size: 140%;
	font-weight: bold;
}

.comment {
	color: #999;
}

.em {
	font-weight: bold;
	color: #420066;
	color: #000;
	font-size: 130%;
	font-size: 100%;
}

</style>
</head>
<body>

<div>
    <a href="/index.html">home</a> &#8227;
	<a href="#number">Number</a> &bull;
	<a href="#string">String</a> &bull;
	<a href="#number-to-string">Number&lt;-&gt;String</a> &bull;
	<a href="#boolean">Boolean</a> &bull;
	<a href="#date">Date</a> &bull;
	<a href="#math">Math</a> &bull;
	<a href="#array">Array</a> &bull;
	<a href="#function">Function</a> &bull;
	<a href="#logic">logic</a> &bull;
	<a href="#object">Object</a> &bull;
	<a href="#type">type</a> &bull;
	<a href="#object-orientation">object-orientation</a> &bull;
	<a href="#exceptions">exceptions</a>
</div>
<br>
%s

<hr/>
<center><a href="/index.html">Tung Dang</a></center>

<script>
  (function(i,s,o,g,r,a,m){i['GoogleAnalyticsObject']=r;i[r]=i[r]||function(){
  (i[r].q=i[r].q||[]).push(arguments)},i[r].l=1*new Date();a=s.createElement(o),
  m=s.getElementsByTagName(o)[0];a.async=1;a.src=g;m.parentNode.insertBefore(a,m)
  })(window,document,'script','//www.google-analytics.com/analytics.js','ga');

  ga('create', 'UA-194516-1', 'auto');
  ga('send', 'pageview');

</script>

</body>
</html>"""
