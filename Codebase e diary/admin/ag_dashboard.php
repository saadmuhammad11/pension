<?php
/**
 *
 * This file is part of HESK - PHP Help Desk Software.
 *
 * (c) Copyright Klemen Stirn. All rights reserved.
 * https://www.hesk.com
 *
 * For the full copyright and license agreement information visit
 * https://www.hesk.com/eula.php
 *
 */

define('IN_SCRIPT',1);
define('HESK_PATH','../');

/* Get all the required files and functions */
require(HESK_PATH . 'hesk_settings.inc.php');
require(HESK_PATH . 'inc/common.inc.php');
require(HESK_PATH . 'inc/admin_functions.inc.php');
require(HESK_PATH . 'inc/reporting_functions.inc.php');
hesk_load_database_functions();

hesk_session_start();
hesk_dbConnect();
hesk_isLoggedIn();

// Check permissions for this feature
hesk_checkPermission('can_run_reports');

// Should reports be full or limited to own tickets?
$can_run_reports_full = hesk_checkPermission('can_run_reports_full', 0);

// Set default values
define('CALENDAR',1);
define('MAIN_PAGE',1);
define('LOAD_TABS',1);

$selected = array(
	'w'    => array(0=>'',1=>''),
	'time' => array(1=>'',2=>'',3=>'',4=>'',5=>'',6=>'',7=>'',8=>'',9=>'',10=>'',11=>'',12=>''),
    'type' => array(1=>'',2=>'',3=>'',4=>''),
);
$is_all_time = 0;

/* Default this month to date */
$date_from = date('Y-m-d',mktime(0, 0, 0, date("m"), 1, date("Y")));
$date_to = date('Y-m-d');
$input_datefrom = date('m/d/Y', strtotime('last month'));
$input_dateto = date('m/d/Y');

/* Date */
if (!empty($_GET['w']))
{
	$df = preg_replace('/[^0-9]/','', hesk_GET('datefrom') );
    if (strlen($df) == 8)
    {
    	$date_from = substr($df,4,4) . '-' . substr($df,0,2) . '-' . substr($df,2,2);
        $input_datefrom = substr($df,0,2) . '/' . substr($df,2,2) . '/' . substr($df,4,4);
    }
    else
    {
    	$date_from = date('Y-m-d', strtotime('last month') );
    }

	$dt = preg_replace('/[^0-9]/','', hesk_GET('dateto') );
    if (strlen($dt) == 8)
    {
    	$date_to = substr($dt,4,4) . '-' . substr($dt,0,2) . '-' . substr($dt,2,2);
        $input_dateto = substr($dt,0,2) . '/' . substr($dt,2,2) . '/' . substr($dt,4,4);
    }
    else
    {
    	$date_to = date('Y-m-d');
    }

    if ($date_from > $date_to)
    {
        $tmp = $date_from;
        $tmp2 = $input_datefrom;

        $date_from = $date_to;
        $input_datefrom = $input_dateto;

        $date_to = $tmp;
        $input_dateto = $tmp2;

        $note_buffer = $hesklang['datetofrom'];
    }

    if ($date_to > date('Y-m-d'))
    {
    	$date_to = date('Y-m-d');
        $input_dateto = date('m/d/Y');
    }

    $query_string = 'ag_dashboard.php?w=1&amp;datefrom='.urlencode($input_datefrom).'&amp;dateto='.urlencode($input_dateto);
	$selected['w'][1]='checked="checked"';
    $selected['time'][3]='selected="selected"';
}
else
{
	$selected['w'][0]='checked="checked"';
	$_GET['time'] = intval( hesk_GET('time', 3) );

    switch ($_GET['time'])
    {
    	case 1:
			/* Today */
			$date_from = date('Y-m-d');
			$date_to = $date_from;
			$selected['time'][1]='selected="selected"';
            $is_all_time = 1;
        break;

    	case 2:
			/* Yesterday */
			$date_from = date('Y-m-d',mktime(0, 0, 0, date("m"), date("d")-1, date("Y")));
			$date_to = $date_from;
			$selected['time'][2]='selected="selected"';
            $is_all_time = 1;
        break;

    	case 4:
			/* Last month */
			$date_from = date('Y-m-d',mktime(0, 0, 0, date("m")-1, 1, date("Y")));
			$date_to = date('Y-m-d',mktime(0, 0, 0, date("m"), 0, date("Y")));
			$selected['time'][4]='selected="selected"';
        break;

    	case 5:
			/* Last 30 days */
			$date_from = date('Y-m-d',mktime(0, 0, 0, date("m")-1, date("d"), date("Y")));
			$date_to = date('Y-m-d');
			$selected['time'][5]='selected="selected"';
        break;

    	case 6:
			/* This week */
			list($date_from,$date_to)=dateweek(0);
            $date_to = date('Y-m-d');
			$selected['time'][6]='selected="selected"';
        break;

    	case 7:
			/* Last week */
			list($date_from,$date_to)=dateweek(-1);
			$selected['time'][7]='selected="selected"';
        break;

    	case 8:
			/* This business week */
			list($date_from,$date_to)=dateweek(0,1);
            $date_to = date('Y-m-d');
			$selected['time'][8]='selected="selected"';
        break;

    	case 9:
			/* Last business week */
			list($date_from,$date_to)=dateweek(-1,1);
			$selected['time'][9]='selected="selected"';
        break;

    	case 10:
			/* This year */
			$date_from = date('Y').'-01-01';
			$date_to = date('Y-m-d');
			$selected['time'][10]='selected="selected"';
        break;

    	case 11:
			/* Last year */
			$date_from = date('Y')-1 . '-01-01';
			$date_to = date('Y')-1 . '-12-31';
			$selected['time'][11]='selected="selected"';
        break;

    	case 12:
			/* All time */
			$date_from = hesk_getOldestDate();
			$date_to = date('Y-m-d');
			$selected['time'][12]='selected="selected"';
            $is_all_time = 1;
        break;

        default:
        	$_GET['time'] = 3;
			$selected['time'][3]='selected="selected"';
    }

    $query_string = 'ag_dashboard.php?w=0&amp;time='.$_GET['time'];
}

unset($tmp);




/* Type */
$type = intval( hesk_GET('type', 1) );
if (isset($selected['type'][$type]))
{
	$selected['type'][$type] = 'selected="selected"';
}

// Setup date SQL so we don't have to call functions several times
$hesk_settings['dt_sql'] = " `dt` BETWEEN '" . hesk_dbEscape($date_from) . " 00:00:00' AND '" . hesk_dbEscape($date_to) . " 23:59:59' ";

/* Print header */
require_once(HESK_PATH . 'inc/header.inc.php');

/* Print main manage users page */
require_once(HESK_PATH . 'inc/show_admin_nav.inc.php');

/* This will handle error, success and notice messages */
hesk_handle_messages();
?>
<div class="main__content reports">
    <form action="ag_dashboard.php" method="get" name="form1">
        <div class="reports__head">
            <h2>
				Pension Dashboard
                <div class="tooltype right out-close">
                    <svg class="icon icon-info">
                        <use xlink:href="<?php echo HESK_PATH; ?>img/sprite.svg#icon-info"></use>
                    </svg>
                    <div class="tooltype__content">
                        <div class="tooltype__wrapper">
                            Pension Dashboard lets you run several reports and see ticket statistics in a chosen date range. 
                        </div>
                    </div>
                </div>
            </h2>
        </div>
		<?php $get_query = hesk_dbQuery("SELECT * FROM `hesk_ag_projects` WHERE status=1 ORDER BY department ASC "); ?>
		<div class="reports__type">
            <h4>Department</h4>
            <div class="dropdown-select center out-close">
                <select name="department">
                    <option value="">Select Department</option>
					<?php
            		while ($row = hesk_dbFetchAssoc($get_query)){ ?>
                    	<option value="<?php echo $row['dept_abbreviation']; ?>" <?php if($_GET['department']==$row['dept_abbreviation']){ echo 'selected'; } ?> ><?php echo $row['department']; ?></option>
					<?php 
					} ?>
                </select>
            </div>
        </div>
        <div class="reports__range">
            <h4><?php echo $hesklang['dtrg']; ?></h4>
            <div class="reports__range_form form">
                <div class="radio-list">
                    <div class="radio-custom">
                        <input type="radio" name="w" value="0" id="sw0" <?php echo $selected['w'][0]; ?>>
                        <label for="sw0">&nbsp;</label>
                        <div class="dropdown-select center out-close">
                            <select name="time" onclick="document.getElementById('sw0').checked = true" onchange="document.getElementById('sw0').checked = true" style="margin-top:5px;margin-bottom:5px;">
                                <option value="1" <?php echo $selected['time'][1]; ?>><?php echo $hesklang['r1']; ?> (<?php echo $hesklang['d'.date('w')]; ?>)</option>
                                <option value="2" <?php echo $selected['time'][2]; ?>><?php echo $hesklang['r2']; ?> (<?php echo $hesklang['d'.date('w',mktime(0, 0, 0, date('m'), date('d')-1, date('Y')))]; ?>)</option>
                                <option value="3" <?php echo $selected['time'][3]; ?>><?php echo $hesklang['r3']; ?> (<?php echo $hesklang['m'.date('n')]; ?>)</option>
                                <option value="4" <?php echo $selected['time'][4]; ?>><?php echo $hesklang['r4']; ?> (<?php echo $hesklang['m'.date('n',mktime(0, 0, 0, date('m')-1, 1, date('Y')))]; ?>)</option>
                                <option value="5" <?php echo $selected['time'][5]; ?>><?php echo $hesklang['r5']; ?></option>
                                <option value="6" <?php echo $selected['time'][6]; ?>><?php echo $hesklang['r6']; ?></option>
                                <option value="7" <?php echo $selected['time'][7]; ?>><?php echo $hesklang['r7']; ?></option>
                                <option value="8" <?php echo $selected['time'][8]; ?>><?php echo $hesklang['r8']; ?></option>
                                <option value="9" <?php echo $selected['time'][9]; ?>><?php echo $hesklang['r9']; ?></option>
                                <option value="10" <?php echo $selected['time'][10]; ?>><?php echo $hesklang['r10']; ?> (<?php echo date('Y'); ?>)</option>
                                <option value="11" <?php echo $selected['time'][11]; ?>><?php echo $hesklang['r11']; ?> (<?php echo date('Y',mktime(0, 0, 0, date('m'), date('d'), date('Y')-1)); ?>)</option>
                                <option value="12" <?php echo $selected['time'][12]; ?>><?php echo $hesklang['r12']; ?></option>
                            </select>
                        </div>
                    </div>
                    <div class="radio-custom">
                        <input type="radio" name="w" value="1" id="sw1" <?php echo $selected['w'][1]; ?>>
                        <label for="sw1">&nbsp;</label>
                        <?php echo $hesklang['from']; ?>
                        <section class="param calendar" style="margin-left: 10px; margin-right: 10px">
                            <div class="calendar--button">
                                <button type="button" onclick="document.getElementById('sw1').checked = true">
                                    <svg class="icon icon-calendar">
                                        <use xlink:href="<?php echo HESK_PATH; ?>img/sprite.svg#icon-calendar"></use>
                                    </svg>
                                </button>
                                <input name="datefrom"
                                       id="datefrom"
                                    <?php if ($input_datefrom) {echo 'value="'.$input_datefrom.'"';} ?>
                                       type="text" class="datepicker">
                            </div>
                            <div class="calendar--value" <?php echo ($input_datefrom ? 'style="display: block"' : ''); ?>>
                                <span><?php echo $input_datefrom; ?></span>
                                <i class="close">
                                    <svg class="icon icon-close">
                                        <use xlink:href="<?php echo HESK_PATH; ?>img/sprite.svg#icon-close"></use>
                                    </svg>
                                </i>
                            </div>
                        </section>
                        <?php echo $hesklang['to']; ?>
                        <section class="param calendar" style="margin-left: 10px;">
                            <div class="calendar--button">
                                <button type="button" onclick="document.getElementById('sw1').checked = true">
                                    <svg class="icon icon-calendar">
                                        <use xlink:href="<?php echo HESK_PATH; ?>img/sprite.svg#icon-calendar"></use>
                                    </svg>
                                </button>
                                <input name="dateto"
                                       id="dateto"
                                    <?php if ($input_dateto) {echo 'value="'.$input_dateto.'"';} ?>
                                       type="text" class="datepicker">
                            </div>
                            <div class="calendar--value" <?php echo ($input_dateto ? 'style="display: block"' : ''); ?>>
                                <span><?php echo $input_dateto; ?></span>
                                <i class="close">
                                    <svg class="icon icon-close">
                                        <use xlink:href="<?php echo HESK_PATH; ?>img/sprite.svg#icon-close"></use>
                                    </svg>
                                </i>
                            </div>
                        </section>
                    </div>
                </div>
            </div>
        </div>
        <div class="reports__type">
            <button class="btn btn-full" ripple="ripple">Search</button>
        </div>
        <input type="hidden" name="token" value="<?php hesk_token_echo(); ?>">
    </form>

<?php

	if ($date_from == $date_to)
	{
		?>
		<h2 style="margin-top: 20px; margin-bottom: 20px"><?php echo hesk_dateToString($date_from,0); ?></h2>
		<?php
	}
	else
	{
		?>
		<h2 style="margin-top: 20px; margin-bottom: 20px"><?php echo hesk_dateToString($date_from,0); ?> - <?php echo hesk_dateToString($date_to,0); ?></h2> 
		<?php
	}

	// Show a note if reports are limited
	if ( ! $can_run_reports_full)
	{
		echo "<p>{$hesklang['roo']}</p>";
	}

	$qs='';
	if($date_from!=''){
		$date_from = date('Y-m-d',strtotime($date_from));
		$from_where = " AND rt.created_at>='".$date_from."'"; 
		$qs .= "&datefrom=".$date_from;
	}else{         
		$from_where = ''; 
	}
  
	if($date_to!=''){
		$date_to = date('Y-m-d',strtotime($date_to));
		$to_where = " AND rt.created_at<='".$date_to."'"; 
		$qs .= "&dateto=".$date_to;
	}else{         
		$to_where = ''; 
	}

	if($_GET['department']!=''){
		$department=$_GET['department'];
		$where_department=" AND rt.department= '".$department."' ";	
		$qs .= "&department=".$department;
	}else{
		$department='';	
		$where_department='';	
	}
//   if($date_from!='' && $date_to!=''){
// 	$date1 = $date_from;
// 	$date2 = $date_to;
// 	$diff = abs(strtotime($date2) - strtotime($date1));
// 	$daysFinal = floor($diff / (60*60*24));
// 	$data['days'] = $daysFinal;
//   }


$res = hesk_dbQuery("
        SELECT
            SUM( CASE
                WHEN ( rt.status IN(1,4,6,7) $from_where $to_where $where_department) 
                THEN 1 
                ELSE 0 
            END) AS appliedPension,
            SUM( CASE
                WHEN ( rt.status=6 $from_where $to_where $where_department) 
                THEN 1 
                ELSE 0 
            END) AS agOfficerVerified,
            SUM( CASE
                WHEN ( rt.status IN(1,4) $from_where $to_where $where_department) 
                THEN 1 
                ELSE 0 
            END) AS pending_agoffice,
            SUM( CASE
                WHEN ( rt.status=7 $from_where $to_where $where_department) 
                THEN 1 
                ELSE 0 
            END) AS reject_agoffice
        FROM `hesk_ag_penrabbitmq` rt");

        //print_r($res);exit;
while ($row = hesk_dbFetchAssoc($res))
{
?>
	<section class="card-sec">
		<div class="container">                
		<h3>Pension Application Status at AG Office</h3>
			<div class="card-panel">
			<div class="row">
				<div class="form-group col-md-3 col-sm-6">
					<div class="card-widget ag-card">
						<h2><a target="_blank" href="<?php echo HESK_PATH; ?>admin/ag_dashboard_detail.php?status=0<?php echo $qs; ?>"><?php echo $row['appliedPension']; ?></a></h2>
						<h4>Received</h4>
						<div class="circle_decor1"></div>
						<div class="circle_decor2"></div>
						<div class="circle_decor3"></div>
					</div>
				</div>
							<div class="form-group col-md-3 col-sm-6">
					<div class="card-widget process-card">
						<h2><a target="_blank" href="<?php echo HESK_PATH; ?>admin/ag_dashboard_detail.php?status=3<?php echo $qs; ?>"><?php echo $row['pending_agoffice']; ?></a></h2>
						<h4>In-process</h4>
						<div class="circle_decor1"></div>
						<div class="circle_decor2"></div>
						<div class="circle_decor3"></div>
					</div>
				</div>
				<div class="form-group col-md-3 col-sm-6">
					<div class="card-widget">
						<h2><a target="_blank" href="<?php echo HESK_PATH; ?>admin/ag_dashboard_detail.php?status=1<?php echo $qs; ?>"><?php echo $row['agOfficerVerified']; ?></a></h2>
						<h4>Approved</h4>
						<div class="circle_decor1"></div>
						<div class="circle_decor2"></div>
						<div class="circle_decor3"></div>
					</div>
				</div>
				<div class="form-group col-md-3">
					<div class="card-widget rej-card">
						<h2><a target="_blank" href="<?php echo HESK_PATH; ?>admin/ag_dashboard_detail.php?status=2<?php echo $qs; ?>"><?php echo $row['reject_agoffice']; ?></a></h2>
						<h4>Rejected</h4>
						<div class="circle_decor1"></div>
						<div class="circle_decor2"></div>
						<div class="circle_decor3"></div>
					</div>
				</div>
			</div>             
			</div>
		</div>
	</section>
<?php } 

$res1 = hesk_dbQuery("
				SELECT
					SUM(CASE WHEN DATE(rt.created_at) BETWEEN DATE_SUB(CURDATE(), INTERVAL 3 DAY) AND DATE_SUB(CURDATE(), INTERVAL 1 DAY) THEN 1 ELSE 0 END) AS pension3,
					SUM(CASE WHEN DATE(rt.created_at) BETWEEN DATE_SUB(CURDATE(), INTERVAL 6 DAY) AND DATE_SUB(CURDATE(), INTERVAL 4 DAY) THEN 1 ELSE 0 END) AS pension6,
					SUM(CASE WHEN DATE(rt.created_at) BETWEEN DATE_SUB(CURDATE(), INTERVAL 9 DAY) AND DATE_SUB(CURDATE(), INTERVAL 7 DAY) THEN 1 ELSE 0 END) AS pension9,
					SUM(CASE WHEN DATE(rt.created_at) <= DATE_SUB(CURDATE(), INTERVAL 10 DAY) THEN 1 ELSE 0 END) AS pension12
				FROM
					hesk_ag_penrabbitmq rt
				WHERE
					rt.status IN(1,4)  $where_department
					");
while ($row1 = hesk_dbFetchAssoc($res1))
{
	$g1=$row1['pension3'];
	$g2=$row1['pension6'];
	$g3=$row1['pension9'];
	$g4=$row1['pension12'];
}

$res2 = hesk_dbQuery("
				SELECT
					SUM(CASE WHEN DATE(rt.created_at) BETWEEN DATE_SUB(CURDATE(), INTERVAL 3 DAY) AND DATE_SUB(CURDATE(), INTERVAL 1 DAY) THEN 1 ELSE 0 END) AS pension3,
					SUM(CASE WHEN DATE(rt.created_at) BETWEEN DATE_SUB(CURDATE(), INTERVAL 6 DAY) AND DATE_SUB(CURDATE(), INTERVAL 4 DAY) THEN 1 ELSE 0 END) AS pension6,
					SUM(CASE WHEN DATE(rt.created_at) BETWEEN DATE_SUB(CURDATE(), INTERVAL 9 DAY) AND DATE_SUB(CURDATE(), INTERVAL 7 DAY) THEN 1 ELSE 0 END) AS pension9,
					SUM(CASE WHEN DATE(rt.created_at) <= DATE_SUB(CURDATE(), INTERVAL 10 DAY) THEN 1 ELSE 0 END) AS pension12
				FROM
					hesk_ag_penrabbitmq rt
				WHERE
					rt.status=6 $where_department");


while ($row2 = hesk_dbFetchAssoc($res2))
{
	$g5=$row2['pension3'];
	$g6=$row2['pension6'];
	$g7=$row2['pension9'];
	$g8=$row2['pension12'];
}
?>
<section class="card-sec" >
    <div class="container">  
        <!-- <h3>Pension Application Progress in AG-Office</h3>               -->
		<div class="row">
			<div class="col-md-6">
			<h3>Status of In-Process Applications</h3>
				<div class="card-panel">
					<div class="graphbox" >
						<div id="seniority_stat" ></div>
					</div>
				</div>
			</div>
			<div class="col-md-6">
			<h3>Status of Approved Applications</h3>
				<div class="card-panel">
					<div class="graphbox" >
						<div id="retirment_app"></div>
					</div> 
				</div>         
			</div>
		</div>
<section class="card-sec" >
    <div class="container">  
        <div class="row">
			<div class="col-md-12">
			<h3>Status of In-Process Applications Department Wise</h3>
				<div class="card-panel">
					<div class="graphbox" >
						<div id="inprocess_department" ></div>
					</div>
				</div>
			</div>
		</div>
	</div>
</section>
<section class="card-sec" >
    <div class="container">  
        <div class="row">
			<div class="col-md-12">
			<h3>Status of Approved Applications Department Wise</h3>
				<div class="card-panel">
					<div class="graphbox" >
						<div id="approved_department"></div>
					</div> 
				</div>         
			</div>
		</div>
    </div>
</section>
<section class="card-sec" >
    <div class="container">  
        <div class="row">
			<div class="col-md-12">
			<h3>Status of Return Applications Department Wise</h3>
				<div class="card-panel">
					<div class="graphbox" >
						<div id="return_department"></div>
					</div> 
				</div>         
			</div>
		</div>
    </div>
</section>
<link rel="stylesheet" href="<?php echo HESK_PATH; ?>css/bootstrap.min.css">
<link rel="stylesheet" href="<?php echo HESK_PATH; ?>css/style.css">
<style type="text/css">
  .card-widget h2 a{
    font-size: 48px;
    font-weight: bold;
    line-height: 1.2;
    margin-top: 0;
    margin-bottom: 0;
    color: #fff !important;
  }
.navbar-static-top {
    z-index: 1!important;
}
</style>
<!-- <script src="<?php echo HESK_PATH; ?>js/jquery.min.js"></script> -->
<!-- <script src="https://code.jquery.com/ui/1.12.1/jquery-ui.min.js" integrity="sha256-VazP97ZCwtekAsvgPBSUwPFKdrwD3unUfSGVYrahUqU=" crossorigin="anonymous"></script> -->
<!-- <link rel="stylesheet" href="https://code.jquery.com/ui/1.12.1/themes/base/jquery-ui.css"> -->
<script src="<?php echo HESK_PATH; ?>js/highcharts/highcharts.js"></script> 
<script src="<?php echo HESK_PATH; ?>js/highcharts/highcharts.js"></script> 
<script src="<?php echo HESK_PATH; ?>js/highcharts/modules/highcharts-more.js"></script>
<script src="<?php echo HESK_PATH; ?>js/highcharts/modules/funnel.js"></script>
<script src="<?php echo HESK_PATH; ?>js/highcharts/proj4.js"></script>
<script src="<?php echo HESK_PATH; ?>js/highcharts/modules/map.js"></script>
<script src="<?php echo HESK_PATH; ?>js/highcharts/modules/sunburst.js"></script>
<script src="<?php echo HESK_PATH; ?>js/highcharts/modules/highcharts-3d.js"></script>
<script src="<?php echo HESK_PATH; ?>js/highcharts/modules/cylinder.js"></script>
<script src="<?php echo HESK_PATH; ?>js/highcharts/modules/heatmap.js"></script>
<script src="<?php echo HESK_PATH; ?>js/highcharts/modules/treemap.js"></script>
<script src="<?php echo HESK_PATH; ?>js/highcharts/modules/exporting.js"></script>
<script src="<?php echo HESK_PATH; ?>js/highcharts/modules/offline-exporting.js"></script>
<script src="<?php echo HESK_PATH; ?>js/highcharts/modules/export-data.js"></script>
<script src="<?php echo HESK_PATH; ?>js/highcharts/modules/data.js"></script>
<script src="<?php echo HESK_PATH; ?>js/highcharts/modules/drilldown.js"></script>
<script type="text/javascript">
    $( document ).ready(function() {
    	var theme1 = {
               colors: ["#A8D7A9", "#69BE6D", "#234F32", "teal", "#afc2ca", "#38b6c4", "#b4651d",
                  "#55BF3B", "#DF5353", "teal", "#afc2ca"],
               chart: {
                   theme: "SandSignika",
                  backgroundColor: null,
                  style: {
                     fontFamily: "Signika, serif"
                  }
               },
               title: {
                  style: {
                     color: 'black',
                     fontSize: '16px',
                     fontWeight: 'bold'
                  }
               },
               subtitle: {
                  style: {
                     color: 'black'
                  }
               },
               tooltip: {
                  borderWidth: 0
               },
               legend: {
                  itemStyle: {
                     fontWeight: 'bold',
                     fontSize: '13px'
                  }
               },
               xAxis: {
                  labels: {
                     style: {
                        color: '#6e6e70'
                     }
                  }
               },
               yAxis: {
                  labels: {
                     style: {
                        color: '#6e6e70'
                     }
                  }
               },
               plotOptions: {
                  series: {
                     shadow: true
                  },
                  candlestick: {
                     lineColor: '#404048'
                  },
                  map: {
                     shadow: false
                  }
               },

               // Highstock specific
               navigator: {
                  xAxis: {
                     gridLineColor: '#D0D0D8'
                  }
               },
               rangeSelector: {
                  buttonTheme: {
                     fill: 'white',
                     stroke: '#C0C0C8',
                     'stroke-width': 1,
                     states: {
                        select: {
                           fill: '#D0D0D8'
                        }
                     }
                  }
               },
               scrollbar: {
                  trackBorderColor: '#C0C0C8'
               },

               // General
               background2: '#E0E0E8'
               
    	};
		var seniority_stat= {
			chart: {
				type: 'column'
			},
			title: {
				text: ''
			},
			subtitle: {
				text: ''
			},
			xAxis: {
				type: 'category',
				title: {
					text: 'Days'
				},
				labels: {
					rotation: -45,
					style: {
						fontSize: '13px',
						fontFamily: 'Verdana, sans-serif'
					}
				}
			},
			yAxis: {
				min: 0,
				title: {
					text: 'Applications'
				}
			},
			legend: {
				enabled: false
			},
			tooltip: {
				pointFormat: 'Total: <b>{point.y} </b>'
			},
			plotOptions: {
				series: {
					cursor: 'pointer',
					point: {
						events: {
							click: function () {
								//location.href = this.options.url;
								window.open(this.options.url, '_blank');
							}
						}
					}
				}
			},
			series: [{
				name: 'Pension',
				// data: [
				//     ['1-3', ],
				//     ['3-6', ],
				//     ['6-9', ],
				//     ['9-12(onwards)', ]
				// ],
				data: [{
					y: <?php echo ($g1!=''?$g1:0); ?>,
					name: '1-3',
					url: '<?php echo HESK_PATH; ?>admin/ag_dashboard_detail.php?status=4&department=<?php echo $department; ?>',
					color:'#006400'
				}, {
					y: <?php echo ($g2!=''?$g2:0); ?>,
					name: '4-6',
					url: '<?php echo HESK_PATH; ?>admin/ag_dashboard_detail.php?status=5&department=<?php echo $department; ?>',
					color:'#ff9933'
				}, {
					y: <?php echo ($g3!=''?$g3:0); ?>,
					name: '7-9',
					url: '<?php echo HESK_PATH; ?>admin/ag_dashboard_detail.php?status=6&department=<?php echo $department; ?>',
					color:'#000080'
				},
				{
					y: <?php echo ($g4!=''?$g4:0); ?>,
					name: '10 & Above',
					url: '<?php echo HESK_PATH; ?>admin/ag_dashboard_detail.php?status=7&department=<?php echo $department; ?>',
					color:'#ff0000'
				}

			],
				dataLabels: {
					enabled: true,
					rotation: 0,
					//color: '#FFFFFF',
					align: 'right',
					format: '{point.y}', // one decimal
					y: 0, // 10 pixels down from the top
					style: {
						fontSize: '13px',
						fontFamily: 'Verdana, sans-serif'
					}
				}
			}]
		};
		$('#seniority_stat').highcharts(Highcharts.merge(seniority_stat, theme1)); 

		var retirment_app= {
            chart: {
                plotBackgroundColor: null,
                plotBorderWidth: null,
                plotShadow: false,
                type: 'pie'
            },
            title: {
                text: ''
            },
            tooltip: {
                pointFormat: '{series.name}: <b>{point.y}</b>'
            },
            accessibility: {
                point: {
                    valueSuffix: ''
                }
            },
            plotOptions: {
                pie: {
                    allowPointSelect: true,
                    cursor: 'pointer',
                    dataLabels: {
                        enabled: false
                    },
                    showInLegend: true
                },
                series: {
                    cursor: 'pointer',
                    point: {
                        events: {
                            click: function () {
                                //location.href = this.options.url;
                                window.open(this.options.url, '_blank');
                            }
                        }
                    }
                }
            },
            series: [{
                name: 'Total',
                colorByPoint: true,
                data: [{
                    name: '1-3',
                    y: <?php echo ($g5!=''?$g5:0); ?>,
                    url: '<?php echo HESK_PATH; ?>admin/ag_dashboard_detail.php?status=8&department=<?php echo $department; ?>',
                    sliced: true,
                    selected: true
                }, {
                    name: '4-6',
                    y: <?php echo ($g6!=''?$g6:0); ?>,
                    url: '<?php echo HESK_PATH; ?>admin/ag_dashboard_detail.php?status=9&department=<?php echo $department; ?>'       
                }, 
                    {
                    name: '7-9',
                    y: <?php echo ($g7!=''?$g7:0); ?>,
                    url: '<?php echo HESK_PATH; ?>admin/ag_dashboard_detail.php?status=10&department=<?php echo $department; ?>'
                }, 
                    {
                    name: '10 & Above',
                    y: <?php echo ($g8!=''?$g8:0); ?>,
                    url: '<?php echo HESK_PATH; ?>admin/ag_dashboard_detail.php?status=11&department=<?php echo $department; ?>'       
                }]
            }]
        };
        $('#retirment_app').highcharts(Highcharts.merge(retirment_app, theme1));


        var inprocess_department= {
			chart: {
				type: 'column'
			},
			title: {
				text: ''
			},
			subtitle: {
				text: ''
			},
			xAxis: {
				type: 'category',
				title: {
					text: 'Department'
				},
				labels: {
					rotation: -45,
					style: {
						fontSize: '13px',
						fontFamily: 'Verdana, sans-serif'
					}
				}
			},
			yAxis: {
				min: 0,
				title: {
					text: 'Applications'
				}
			},
			legend: {
				enabled: false
			},
			tooltip: {
				pointFormat: 'Total: <b>{point.y} </b>'
			},
			plotOptions: {
				series: {
					cursor: 'pointer',
					point: {
						events: {
							click: function () {
								//location.href = this.options.url;
								window.open(this.options.url, '_blank');
							}
						}
					}
				}
			},
			series: [{
				name: 'Pension',
				data: [
                <?php 
				$res3 = hesk_dbQuery("
				SELECT
					department,
					count(rt.department) as total
				FROM
					hesk_ag_penrabbitmq rt
				WHERE
					rt.status IN(1,4) GROUP BY rt.department ORDER BY rt.department ASC");
				$i=0;
                while ($row3 = hesk_dbFetchAssoc($res3))
                { 
                        $total=$row3['total'];
                        $dep=$row3['department']; 
				?>
                    {
                        y: <?php echo ($total!=''?$total:0); ?>,
                        name: '<?php echo $dep; ?>',
                        url: '<?php echo HESK_PATH; ?>admin/ag_dashboard_detail.php?status=12&department=<?php echo $dep; ?>',
						<?php if($i==0){
						?>
						color:'#3A7AFE' 
						<?php
						}else if($i==1){
						?>
						color:'#FF9F00' 
						<?php
						}else if($i==2){
							?>
						color:'#10CA93' 
						<?php
						}else if($i==3){
							?>
						color:'#F25767' 
						<?php
						}else{
							?>
						color:'#3A7AFE' 
						<?php
							$i=0;
						} ?>
                        
                    }, 
                <?php 
				$i++;
				} ?>
			],
				dataLabels: {
					enabled: true,
					rotation: 0,
					//color: '#FFFFFF',
					align: 'right',
					format: '{point.y}', // one decimal
					y: 0, // 10 pixels down from the top
					style: {
						fontSize: '13px',
						fontFamily: 'Verdana, sans-serif'
					}
				}
			}]
		};
		$('#inprocess_department').highcharts(Highcharts.merge(inprocess_department, theme1)); 

        var approved_department= {
			chart: {
				type: 'column'
			},
			title: {
				text: ''
			},
			subtitle: {
				text: ''
			},
			xAxis: {
				type: 'category',
				title: {
					text: 'Department'
				},
				labels: {
					rotation: -45,
					style: {
						fontSize: '13px',
						fontFamily: 'Verdana, sans-serif'
					}
				}
			},
			yAxis: {
				min: 0,
				title: {
					text: 'Applications'
				}
			},
			legend: {
				enabled: false
			},
			tooltip: {
				pointFormat: 'Total: <b>{point.y} </b>'
			},
			plotOptions: {
				series: {
					cursor: 'pointer',
					point: {
						events: {
							click: function () {
								//location.href = this.options.url;
								window.open(this.options.url, '_blank');
							}
						}
					}
				}
			},
			series: [{
				name: 'Pension',
				data: [
					<?php 
				$res3 = hesk_dbQuery("
				SELECT
					department,
					count(rt.department) as total
				FROM
					hesk_ag_penrabbitmq rt
				WHERE
					rt.status=6 GROUP BY rt.department ORDER BY rt.department ASC");

				$i=0;
                while ($row3 = hesk_dbFetchAssoc($res3))
                { 
                        $total=$row3['total'];
                        $dep=$row3['department']; 
				?>
                    {
                        y: <?php echo ($total!=''?$total:0); ?>,
                        name: '<?php echo $dep; ?>',
                        url: '<?php echo HESK_PATH; ?>admin/ag_dashboard_detail.php?status=13&department=<?php echo $dep; ?>',
                        <?php if($i==0){
						?>
						color:'#3A7AFE' 
						<?php
						}else if($i==1){
						?>
						color:'#FF9F00' 
						<?php
						}else if($i==2){
							?>
						color:'#10CA93' 
						<?php
						}else if($i==3){
							?>
						color:'#F25767' 
						<?php
						}else{
							?>
						color:'#3A7AFE' 
						<?php
							$i=0;
						} ?>
                    }, 
                <?php
				$i++; 
				} ?>

			],
				dataLabels: {
					enabled: true,
					rotation: 0,
					//color: '#FFFFFF',
					align: 'right',
					format: '{point.y}', // one decimal
					y: 0, // 10 pixels down from the top
					style: {
						fontSize: '13px',
						fontFamily: 'Verdana, sans-serif'
					}
				}
			}]
		};
		$('#approved_department').highcharts(Highcharts.merge(approved_department, theme1)); 

		var return_department= {
			chart: {
				type: 'column'
			},
			title: {
				text: ''
			},
			subtitle: {
				text: ''
			},
			xAxis: {
				type: 'category',
				title: {
					text: 'Department'
				},
				labels: {
					rotation: -45,
					style: {
						fontSize: '13px',
						fontFamily: 'Verdana, sans-serif'
					}
				}
			},
			yAxis: {
				min: 0,
				title: {
					text: 'Applications'
				}
			},
			legend: {
				enabled: false
			},
			tooltip: {
				pointFormat: 'Total: <b>{point.y} </b>'
			},
			plotOptions: {
				series: {
					cursor: 'pointer',
					point: {
						events: {
							click: function () {
								//location.href = this.options.url;
								window.open(this.options.url, '_blank');
							}
						}
					}
				}
			},
			series: [{
				name: 'Pension',
				data: [
					<?php 
				$res4 = hesk_dbQuery("
				SELECT
					department,
					count(rt.department) as total
				FROM
					hesk_ag_penrabbitmq rt
				WHERE
					rt.status=7 GROUP BY rt.department ORDER BY rt.department ASC");

				$i=0;
                while ($row4 = hesk_dbFetchAssoc($res4))
                { 
                        $total=$row4['total'];
                        $dep=$row4['department']; 
				?>
                    {
                        y: <?php echo ($total!=''?$total:0); ?>,
                        name: '<?php echo $dep; ?>',
                        url: '<?php echo HESK_PATH; ?>admin/ag_dashboard_detail.php?status=14&department=<?php echo $dep; ?>',
                        <?php if($i==0){
						?>
						color:'#3A7AFE' 
						<?php
						}else if($i==1){
						?>
						color:'#FF9F00' 
						<?php
						}else if($i==2){
							?>
						color:'#10CA93' 
						<?php
						}else if($i==3){
							?>
						color:'#F25767' 
						<?php
						}else{
							?>
						color:'#3A7AFE' 
						<?php
							$i=0;
						} ?>
                    }, 
                <?php
				$i++; 
				} ?>

			],
				dataLabels: {
					enabled: true,
					rotation: 0,
					//color: '#FFFFFF',
					align: 'right',
					format: '{point.y}', // one decimal
					y: 0, // 10 pixels down from the top
					style: {
						fontSize: '13px',
						fontFamily: 'Verdana, sans-serif'
					}
				}
			}]
		};
		$('#return_department').highcharts(Highcharts.merge(return_department, theme1)); 

	});
</script>  
<?php
require_once(HESK_PATH . 'inc/footer.inc.php'); 
exit();
?>
</div>


