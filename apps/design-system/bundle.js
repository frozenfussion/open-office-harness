/* @ds-bundle: {"format":4,"namespace":"OpenOfficeHarness","components":[{"name":"Button"},{"name":"Input"},{"name":"StatusChip"},{"name":"ChatMessage"},{"name":"DataTable"},{"name":"NavRail"},{"name":"WordRain"}]} */
(function(){
  var KATA="ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝｦ";
  var GLYPHS=(KATA+KATA+"0123456789"+"0123456789"+"ZXKAIHT:.=*+-<>|").split("");
  function pick(){return GLYPHS[(Math.random()*GLYPHS.length)|0]}
  function mount(canvas,opts){
    opts=opts||{};
    var x=canvas.getContext('2d'),W=0,H=0,cell=18,cols=[],acc=0,last=0,stopped=false,ready=false,groundSeen='';
    var reduce=window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches;
    var root=document.documentElement;
    function v(n){return getComputedStyle(root).getPropertyValue(n).trim()}
    function dark(){var t=root.getAttribute('data-theme');if(t)return t!=='light';return !(window.matchMedia&&matchMedia('(prefers-color-scheme: light)').matches)}
    function font(){return (opts.size||16)+'px '+(v('--font-rain')||'"Noto Sans JP", monospace')}
    function size(){
      var r=canvas.getBoundingClientRect(),d=Math.min(window.devicePixelRatio||1,2);
      W=Math.max(1,r.width);H=Math.max(1,r.height);canvas.width=W*d;canvas.height=H*d;x.setTransform(d,0,0,d,0,0);
      cell=(opts.size||16)+2;var n=Math.ceil(W/cell);cols=[];
      for(var i=0;i<n;i++){cols.push({y:-Math.floor(Math.random()*H/cell*1.5),every:1+((Math.random()*3)|0),skip:0,prev:null})}
      groundSeen='';
    }
    function paintGround(alpha){x.globalAlpha=alpha;x.fillStyle=v('--ground')||'#060A08';x.fillRect(0,0,W,H);x.globalAlpha=1}
    function tick(){
      var dk=dark(),g=v('--ground');
      if(g!==groundSeen){paintGround(1);groundSeen=g}
      paintGround(dk?0.085:0.12);
      x.font=font();x.textAlign='center';x.textBaseline='top';
      var trail=dk?v('--phosphor'):v('--ink-muted'),head=dk?v('--ink'):v('--phosphor'),glow=v('--phosphor');
      for(var i=0;i<cols.length;i++){
        var c=cols[i];c.skip++;if(c.skip<c.every)continue;c.skip=0;
        var cx=i*cell+cell/2;
        if(c.prev&&c.prev.y>=0){x.shadowBlur=0;x.fillStyle=trail;x.globalAlpha=dk?0.9:0.7;x.fillText(c.prev.g,cx,c.prev.y*cell)}
        var gch=pick();
        if(c.y>=0){x.globalAlpha=1;x.fillStyle=head;x.shadowColor=glow;x.shadowBlur=dk?10:0;x.fillText(gch,cx,c.y*cell);x.shadowBlur=0}
        c.prev={y:c.y,g:gch};c.y++;
        if(c.y*cell>H&&Math.random()>0.975){c.y=-((Math.random()*8)|0);c.prev=null;c.every=1+((Math.random()*3)|0)}
      }
      for(var k=0;k<Math.max(2,cols.length/6);k++){
        var j=(Math.random()*cols.length)|0,col=cols[j];if(!col||col.y<4)continue;
        var ry=col.y-2-((Math.random()*Math.min(col.y-2,14))|0);
        x.globalAlpha=0.45;x.fillStyle=trail;x.fillText(pick(),j*cell+cell/2,ry*cell);
      }
      x.globalAlpha=1;
    }
    function loop(ts){if(stopped)return;if(!document.hidden&&ready){acc+=last?Math.min(ts-last,200):16;while(acc>=55){tick();acc-=55}}last=ts;requestAnimationFrame(loop)}
    canvas.style.opacity=String(opts.intensity!=null?opts.intensity:(dark()?0.6:0.35));
    size();window.addEventListener('resize',size);
    function start(){ready=true;if(reduce||opts.still){for(var s=0;s<90;s++)tick()}else requestAnimationFrame(loop)}
    try{(document.fonts&&document.fonts.load)?Promise.race([document.fonts.load(font(),'ｱ0'),new Promise(function(r){setTimeout(r,1500)})]).then(start,start):start()}catch(e){start()}
    return {stop:function(){stopped=true;window.removeEventListener('resize',size)}};
  }
  window.OpenOfficeHarness={WordRain:{mount:mount,glyphs:GLYPHS},Button:{className:'ooh-btn'},Input:{className:'ooh-input'},StatusChip:{className:'ooh-chip'},ChatMessage:{className:'ooh-msg'},DataTable:{className:'ooh-table'},NavRail:{className:'ooh-nav'}};
})();
