<?php

define('IN_SCRIPT', 1);
define('HESK_PATH', '../');

/* Get all the required files and functions */
require(HESK_PATH . 'hesk_settings.inc.php');
require(HESK_PATH . 'inc/common.inc.php');
require(HESK_PATH . 'inc/admin_functions.inc.php');
hesk_load_database_functions();

hesk_session_start();
hesk_dbConnect();
hesk_isLoggedIn();

define('CALENDAR', 1);
define('MAIN_PAGE', 1);
define('AUTO_RELOAD', 1);

/* Print header */
require_once(HESK_PATH . 'inc/header.inc.php');

$href = 'admin_main.php';
/* Print admin navigation */
require_once(HESK_PATH . 'inc/show_admin_nav.inc.php');
// Load custom fields
require_once(HESK_PATH . 'inc/custom_fields.inc.php');

// Load statuses
require_once(HESK_PATH . 'inc/statuses.inc.php');

//MySQL QUERY

$get_query = hesk_dbQuery("select * from `".hesk_dbEscape($hesk_settings['db_pfix'])."rabbitmq` where status=1 ");

?>

<link rel="stylesheet" media="all" href="https://cdn.datatables.net/1.11.3/css/jquery.dataTables.min.css">
<script src='https://cdn.datatables.net/1.11.3/js/jquery.dataTables.min.js'></script>
<div class="table-wrap">
    <table class="table sindu-table ticket-list sindu_origin_table" id="sync_tickets">
        <thead>
            <tr>
                <th>#</th>
                <th>Officer ID</th>
                <th>Retirement ID</th>
                <th>CNIC</th>
                <th>Name</th>
                <th>Personal #</th>
                <th>Contact</th>
                <!-- <th>Status</th> -->
                <th>Action</th>
            </tr>
        </thead>
        <tbody>
            
            <?php
            $count=1;
            while ($row = hesk_dbFetchAssoc($get_query)){ ?> 
                
            <tr>
                <td><?=$count?></td>
                <td><?=$row['officer_id']?></td>
                <td><?=$row['retirement_id']?></td>
                <td><?=$row['cnic']?></td>
                <td><?=$row['firstname']?></td>
                <td><?=$row['personal_no']?></td>
                <td><?=$row['opr_phone']?></td>
                <!--<td><span class="replied"><?//=$row['status']==1?'Ticket Not Added':'Ticket Added'?></span></td>-->
                <td>
                    <?php
                        if($row['status']==1) {
                            echo "<a href='../admin/new_ticket.php?category=2&cnic=".$row['cnic']."&firstname=".$row['firstname']."&officer_id=".$row['officer_id']."&retirement_id=".$row['retirement_id']."&personal_no=".$row['personal_no']."&opr_phone=".$row['opr_phone']."'> Create Ticket </a>";
                        }else{
                            echo "-";
                        }
                    ?>
                </td>
            </tr>
                
            <?php $count++; } ?>

        </tbody>
    </table>
</div>
<script>
    $(document).ready(function () {
        $('#sync_tickets').DataTable();
    });
</script>

<?php
/* Clean unneeded session variables */
hesk_cleanSessionVars('hide');

require_once(HESK_PATH . 'inc/footer.inc.php');
exit();
?>
