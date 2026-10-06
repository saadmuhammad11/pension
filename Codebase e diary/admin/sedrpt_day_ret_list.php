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

define('IN_SCRIPT', 1);
define('HESK_PATH', '../');

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
define('CALENDAR', 1);
define('MAIN_PAGE', 1);
define('LOAD_TABS', 1);

$selected = array(
    'w'    => array(0 => '', 1 => ''),
    'time' => array(1 => '', 2 => '', 3 => '', 4 => '', 5 => '', 6 => '', 7 => '', 8 => '', 9 => '', 10 => '', 11 => '', 12 => ''),
    'type' => array(1 => '', 2 => '', 3 => '', 4 => ''),
);
$is_all_time = 0;

/* Default this month to date */
$date_from = date('Y-m-d', mktime(0, 0, 0, date("m"), 1, date("Y")));
$date_to = date('Y-m-d');
$input_datefrom = date('m/d/Y', strtotime('last month'));
$input_dateto = date('m/d/Y');

$curl = basename($_SERVER['REQUEST_URI']);
$parts = parse_url($curl);
parse_str($parts['query'], $query);
$start_date = $query['date'];
$end_date = $start_date;


/* Print header */
require_once(HESK_PATH . 'inc/header.inc.php');

/* Print main manage users page */
require_once(HESK_PATH . 'inc/show_admin_nav.inc.php');

// Setup date SQL so we don't have to call functions several times
$hesk_settings['dt_sql'] = " `dt` BETWEEN '" . hesk_dbEscape($start_date) . " 00:00:00' AND '" . hesk_dbEscape($end_date) . " 23:59:59' ";



// SQL query for resolved
$res = hesk_dbQuery("SELECT tick.id,tick.name,tick.custom4 as applicant_name, tick.status,tick.dt, tick.trackid FROM `" . hesk_dbEscape($hesk_settings['db_pfix']) . "tickets` as tick
							INNER JOIN `hesk_ag_penrabbitmq` as rbmq on `tick`.id = rbmq.ticket_id
							WHERE " . ($can_run_reports_full ? '1' : "`owner` = '" . intval($_SESSION['id']) . "'") . " AND  (tick.`status` = '7' or tick.`status` = '3')  AND rbmq.status = '7' AND {$hesk_settings['dt_sql']}");

?>
<div class="main__content reports">
    <div class="reports__table">
        <table id="default-table" class="table sindu-table sindu_origin_table">
            <thead>
                <tr>
                    <th>Sr#</th>
                    <th>Ticket Id</th>
                    <th>Name</th>
                    <th>Applicant Name</th>
                    <th>Status</th>
                    <th>Date</th>
                </tr>
            </thead>
            <tbody>
                <?php $key = 1;
                $random=rand(10000,99999);
                while ($row = hesk_dbFetchAssoc($res)) { ?>
                    <tr>
                        <th><?php echo $key; ?></th>
                        <th><?php echo '<a href="admin_ticket.php?track='.$row['trackid'].'&amp;Refresh='.$random.'">'.$row['id'].'</a>';
                         ?></th>
                        <th><?php echo $row['name']; ?></th>
                        <th><?php echo $row['applicant_name']; ?></th>
                        <th><?php echo ($row['status'] == 3 ? "Returned" : "N/A"); ?></th>
                        <th><?php echo date('Y-m-d', strtotime($row['dt'])); ?></th>

                    </tr>
                <?php $key++;
                } ?>
            </tbody>
        </table>
    </div>
</div>